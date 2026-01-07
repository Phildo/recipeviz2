#!/usr/bin/env python3
"""Recipe Visualizer Backend Server"""

import os
import json
import base64
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import psycopg2
from psycopg2.extras import RealDictCursor
import anthropic
import requests

# Database connection
def get_db():
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'db'),
        database=os.environ.get('DB_NAME', 'recipeviz'),
        user=os.environ.get('DB_USER', 'recipeviz'),
        password=os.environ.get('DB_PASSWORD', 'recipeviz')
    )

# Anthropic client
client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))

SONNET_MODEL = "claude-sonnet-4-20250514"
OPUS_MODEL = "claude-opus-4-20250514"

EXTRACTION_PROMPT = """You are a recipe extraction assistant. Your task is to extract ONLY the recipe content from the provided input and format it as clean markdown.

Remove all:
- Advertisements
- Personal stories/anecdotes
- Navigation elements
- Comments
- Unrelated content

Keep only:
- Recipe title
- Ingredients list
- Step-by-step instructions
- Cooking times
- Serving sizes
- Any essential tips directly related to the recipe

Format as clean markdown with clear sections. Be thorough - capture every cooking step and ingredient."""

STRUCTURING_PROMPT = """You are a recipe structuring assistant. Your task is to convert the recipe into a detailed flow-based representation.

The recipe must be broken down into TRANSFORMS - each transform represents a single action that modifies ingredients or tools.

CRITICAL RULES:
1. Every ingredient/tool state change needs its own transform
2. Use pipe_uid to track items through the flow - inputs use existing pipe_uids, outputs create new ones
3. Tools like ovens need setup transforms (e.g., preheat) before use
4. Passive waits (like oven preheating, dough rising) are transforms with active=false
5. Colors should be hex codes reflecting the ingredient/tool appearance
6. Be granular - "chop and sautee onions" is TWO transforms

Output a JSON object with this exact structure:
{
    "recipe": {
        "name": "Recipe Name",
        "description": "Brief description",
        "servings": 4,
        "total_time_minutes": 60
    },
    "transforms": [
        {
            "inputs": [
                {
                    "ingredient": "ingredient name",  // OR "tool": "tool name"
                    "pipe_uid": 0,
                    "color": "#hexcolor",
                    "unit": "unit name",  // optional for tools
                    "amount": 1.0,  // optional for tools
                    "display_name": "display name"  // optional
                }
            ],
            "transform": {
                "action": "action verb",
                "active": true,
                "name": "short name",
                "description": "details",
                "duration_minutes": 5
            },
            "outputs": [
                {
                    "ingredient": "modified ingredient name",  // OR "tool": "tool name"
                    "pipe_uid": 1,
                    "color": "#hexcolor",
                    "unit": "unit name",
                    "amount": 1.0,
                    "display_name": "display name"
                }
            ]
        }
    ]
}

IMPORTANT:
- Start pipe_uid at 0 and increment for each NEW output
- Base ingredients (not outputs of previous transforms) start with fresh pipe_uids
- When an item passes through multiple transforms, track it via pipe_uid
- Include ALL steps, even simple ones like "add salt"
- Tools remain available after use (knife can chop multiple things)
- Final dish should be the output of the last transform

Return ONLY valid JSON, no explanation."""


def fetch_url_content(url):
    """Fetch content from a URL"""
    try:
        headers = {'User-Agent': 'RecipeViz/1.0'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        raise Exception(f"Failed to fetch URL: {str(e)}")


def extract_recipe_with_sonnet(content, content_type='text'):
    """First pass: Extract recipe markdown using Sonnet"""
    messages = []

    if content_type == 'images':
        # content is a list of base64 images
        image_content = []
        for img_data in content:
            media_type = "image/jpeg"
            if img_data.startswith("data:"):
                # Extract media type from data URL
                match = re.match(r'data:([^;]+);base64,(.+)', img_data)
                if match:
                    media_type = match.group(1)
                    img_data = match.group(2)
            image_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": img_data
                }
            })
        image_content.append({
            "type": "text",
            "text": "Extract the recipe from these images."
        })
        messages = [{"role": "user", "content": image_content}]
    else:
        messages = [{"role": "user", "content": f"Extract the recipe from the following content:\n\n{content}"}]

    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=4096,
        system=EXTRACTION_PROMPT,
        messages=messages
    )

    return response.content[0].text


def structure_recipe_with_opus(markdown_recipe):
    """Second pass: Structure recipe into transforms using Opus"""
    response = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=8192,
        system=STRUCTURING_PROMPT,
        messages=[{"role": "user", "content": markdown_recipe}]
    )

    response_text = response.content[0].text

    # Try to extract JSON from the response
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        match = re.search(r'\{[\s\S]*\}', response_text)
        if match:
            return json.loads(match.group())
        raise Exception("Failed to parse structured recipe JSON")


def get_or_create_ingredient(cursor, name):
    """Get or create an ingredient, return its ID"""
    cursor.execute("SELECT id FROM ingredients WHERE name = %s", (name.lower(),))
    row = cursor.fetchone()
    if row:
        return row['id']
    cursor.execute("INSERT INTO ingredients (name) VALUES (%s) RETURNING id", (name.lower(),))
    return cursor.fetchone()['id']


def get_or_create_tool(cursor, name):
    """Get or create a tool, return its ID"""
    cursor.execute("SELECT id FROM tools WHERE name = %s", (name.lower(),))
    row = cursor.fetchone()
    if row:
        return row['id']
    cursor.execute("INSERT INTO tools (name) VALUES (%s) RETURNING id", (name.lower(),))
    return cursor.fetchone()['id']


def get_or_create_action(cursor, name):
    """Get or create an action, return its ID"""
    cursor.execute("SELECT id FROM actions WHERE name = %s", (name.lower(),))
    row = cursor.fetchone()
    if row:
        return row['id']
    cursor.execute("INSERT INTO actions (name) VALUES (%s) RETURNING id", (name.lower(),))
    return cursor.fetchone()['id']


def get_or_create_unit(cursor, name):
    """Get or create a unit, return its ID"""
    if not name:
        return None
    cursor.execute("SELECT id FROM units WHERE name = %s", (name.lower(),))
    row = cursor.fetchone()
    if row:
        return row['id']
    cursor.execute("INSERT INTO units (name) VALUES (%s) RETURNING id", (name.lower(),))
    return cursor.fetchone()['id']


def save_recipe_to_db(structured_data, distilled_text, source_type, source_url=None):
    """Save the structured recipe to the database"""
    conn = get_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        recipe_info = structured_data['recipe']

        # Insert recipe
        cursor.execute("""
            INSERT INTO recipes (name, source_type, source_url, description, servings, total_time_minutes)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            recipe_info.get('name', 'Untitled Recipe'),
            source_type,
            source_url,
            recipe_info.get('description'),
            recipe_info.get('servings'),
            recipe_info.get('total_time_minutes')
        ))
        recipe_id = cursor.fetchone()['id']

        # Save distilled text
        cursor.execute("""
            INSERT INTO recipe_source_distillations (recipe_id, distilled_text)
            VALUES (%s, %s)
        """, (recipe_id, distilled_text))

        # Process transforms
        for step_order, transform_data in enumerate(structured_data.get('transforms', [])):
            transform = transform_data['transform']

            # Get or create action
            action_id = get_or_create_action(cursor, transform.get('action', 'process'))

            # Insert transform
            cursor.execute("""
                INSERT INTO recipe_transforms (recipe_id, action_id, active, name, description, duration_minutes, step_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                recipe_id,
                action_id,
                transform.get('active', True),
                transform.get('name', ''),
                transform.get('description'),
                transform.get('duration_minutes', 0),
                step_order
            ))
            transform_id = cursor.fetchone()['id']

            # Process inputs
            for io_data in transform_data.get('inputs', []):
                ingredient_id = None
                tool_id = None

                if 'ingredient' in io_data:
                    ingredient_id = get_or_create_ingredient(cursor, io_data['ingredient'])
                elif 'tool' in io_data:
                    tool_id = get_or_create_tool(cursor, io_data['tool'])

                unit_id = get_or_create_unit(cursor, io_data.get('unit'))

                cursor.execute("""
                    INSERT INTO recipe_transform_io
                    (recipe_id, recipe_transform_id, is_output, ingredient_id, tool_id, pipe_uid, display_name, color, unit_id, amount)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    recipe_id,
                    transform_id,
                    False,
                    ingredient_id,
                    tool_id,
                    io_data.get('pipe_uid', 0),
                    io_data.get('display_name'),
                    io_data.get('color'),
                    unit_id,
                    io_data.get('amount')
                ))

            # Process outputs
            for io_data in transform_data.get('outputs', []):
                ingredient_id = None
                tool_id = None

                if 'ingredient' in io_data:
                    ingredient_id = get_or_create_ingredient(cursor, io_data['ingredient'])
                elif 'tool' in io_data:
                    tool_id = get_or_create_tool(cursor, io_data['tool'])

                unit_id = get_or_create_unit(cursor, io_data.get('unit'))

                cursor.execute("""
                    INSERT INTO recipe_transform_io
                    (recipe_id, recipe_transform_id, is_output, ingredient_id, tool_id, pipe_uid, display_name, color, unit_id, amount)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    recipe_id,
                    transform_id,
                    True,
                    ingredient_id,
                    tool_id,
                    io_data.get('pipe_uid', 0),
                    io_data.get('display_name'),
                    io_data.get('color'),
                    unit_id,
                    io_data.get('amount')
                ))

        conn.commit()
        return recipe_id

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def get_recipe(recipe_id):
    """Get a full recipe with all transforms and IO"""
    conn = get_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get recipe
        cursor.execute("SELECT * FROM recipes WHERE id = %s", (recipe_id,))
        recipe = cursor.fetchone()
        if not recipe:
            return None

        # Get distilled text
        cursor.execute("SELECT distilled_text FROM recipe_source_distillations WHERE recipe_id = %s", (recipe_id,))
        distillation = cursor.fetchone()
        recipe['distilled_text'] = distillation['distilled_text'] if distillation else None

        # Get transforms with IO
        cursor.execute("""
            SELECT
                rt.id, rt.action_id, rt.active, rt.name, rt.description, rt.duration_minutes, rt.step_order,
                a.name as action_name
            FROM recipe_transforms rt
            LEFT JOIN actions a ON rt.action_id = a.id
            WHERE rt.recipe_id = %s
            ORDER BY rt.step_order
        """, (recipe_id,))
        transforms = cursor.fetchall()

        for transform in transforms:
            # Get inputs
            cursor.execute("""
                SELECT
                    io.*,
                    i.name as ingredient_name,
                    t.name as tool_name,
                    u.name as unit_name
                FROM recipe_transform_io io
                LEFT JOIN ingredients i ON io.ingredient_id = i.id
                LEFT JOIN tools t ON io.tool_id = t.id
                LEFT JOIN units u ON io.unit_id = u.id
                WHERE io.recipe_transform_id = %s AND io.is_output = false
            """, (transform['id'],))
            transform['inputs'] = cursor.fetchall()

            # Get outputs
            cursor.execute("""
                SELECT
                    io.*,
                    i.name as ingredient_name,
                    t.name as tool_name,
                    u.name as unit_name
                FROM recipe_transform_io io
                LEFT JOIN ingredients i ON io.ingredient_id = i.id
                LEFT JOIN tools t ON io.tool_id = t.id
                LEFT JOIN units u ON io.unit_id = u.id
                WHERE io.recipe_transform_id = %s AND io.is_output = true
            """, (transform['id'],))
            transform['outputs'] = cursor.fetchall()

        recipe['transforms'] = transforms
        return recipe

    finally:
        cursor.close()
        conn.close()


def get_all_recipes():
    """Get list of all recipes (summary only)"""
    conn = get_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT id, name, source_type, description, servings, total_time_minutes, created_at
            FROM recipes
            ORDER BY created_at DESC
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


class RequestHandler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def send_error_json(self, message, status=400):
        self.send_json({'error': message}, status)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/recipes':
            recipes = get_all_recipes()
            self.send_json({'recipes': recipes})

        elif parsed.path.startswith('/api/recipes/'):
            try:
                recipe_id = int(parsed.path.split('/')[-1])
                recipe = get_recipe(recipe_id)
                if recipe:
                    self.send_json({'recipe': recipe})
                else:
                    self.send_error_json('Recipe not found', 404)
            except ValueError:
                self.send_error_json('Invalid recipe ID', 400)

        elif parsed.path == '/api/health':
            self.send_json({'status': 'ok'})

        else:
            self.send_error_json('Not found', 404)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/recipes':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body)
                source_type = data.get('source_type')

                if source_type == 'url':
                    url = data.get('url')
                    if not url:
                        self.send_error_json('URL is required')
                        return

                    # Fetch URL content
                    content = fetch_url_content(url)

                    # First pass: extract recipe
                    distilled_text = extract_recipe_with_sonnet(content, 'text')

                    # Second pass: structure recipe
                    structured_data = structure_recipe_with_opus(distilled_text)

                    # Save to database
                    recipe_id = save_recipe_to_db(structured_data, distilled_text, 'url', url)

                    self.send_json({'recipe_id': recipe_id, 'message': 'Recipe created successfully'})

                elif source_type == 'text':
                    text = data.get('text')
                    if not text:
                        self.send_error_json('Text is required')
                        return

                    # First pass: extract recipe
                    distilled_text = extract_recipe_with_sonnet(text, 'text')

                    # Second pass: structure recipe
                    structured_data = structure_recipe_with_opus(distilled_text)

                    # Save to database
                    recipe_id = save_recipe_to_db(structured_data, distilled_text, 'text')

                    self.send_json({'recipe_id': recipe_id, 'message': 'Recipe created successfully'})

                elif source_type == 'images':
                    images = data.get('images', [])
                    if not images:
                        self.send_error_json('Images are required')
                        return

                    # First pass: extract recipe from images
                    distilled_text = extract_recipe_with_sonnet(images, 'images')

                    # Second pass: structure recipe
                    structured_data = structure_recipe_with_opus(distilled_text)

                    # Save to database
                    recipe_id = save_recipe_to_db(structured_data, distilled_text, 'images')

                    self.send_json({'recipe_id': recipe_id, 'message': 'Recipe created successfully'})

                else:
                    self.send_error_json('Invalid source_type. Must be url, text, or images')

            except json.JSONDecodeError:
                self.send_error_json('Invalid JSON')
            except Exception as e:
                self.send_error_json(str(e), 500)

        else:
            self.send_error_json('Not found', 404)


def main():
    port = int(os.environ.get('PORT', 8000))
    server = HTTPServer(('0.0.0.0', port), RequestHandler)
    print(f"Server running on port {port}")
    server.serve_forever()


if __name__ == '__main__':
    main()
