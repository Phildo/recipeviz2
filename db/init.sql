-- Recipe Visualizer Database Schema

-- Ingredients table (global, reused across recipes)
CREATE TABLE ingredients (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tools table (global, reused across recipes)
CREATE TABLE tools (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Actions table (global, reused across recipes)
CREATE TABLE actions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Units table (global, reused across recipes)
CREATE TABLE units (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Recipes table
CREATE TABLE recipes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL, -- 'url', 'text', 'images'
    source_url TEXT,
    description TEXT,
    servings INTEGER,
    total_time_minutes INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Recipe source distillations (the markdown extracted from first LLM pass)
CREATE TABLE recipe_source_distillations (
    id SERIAL PRIMARY KEY,
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
    distilled_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Recipe transforms (the processing steps)
CREATE TABLE recipe_transforms (
    id SERIAL PRIMARY KEY,
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
    action_id INTEGER REFERENCES actions(id),
    active BOOLEAN NOT NULL DEFAULT TRUE, -- false for passive transforms like "wait"
    name VARCHAR(255) NOT NULL,
    description TEXT,
    duration_minutes REAL DEFAULT 0,
    step_order INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Recipe transform inputs/outputs
CREATE TABLE recipe_transform_io (
    id SERIAL PRIMARY KEY,
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
    recipe_transform_id INTEGER REFERENCES recipe_transforms(id) ON DELETE CASCADE,
    is_output BOOLEAN NOT NULL,
    ingredient_id INTEGER REFERENCES ingredients(id),
    tool_id INTEGER REFERENCES tools(id),
    pipe_uid INTEGER NOT NULL,
    display_name VARCHAR(255),
    color VARCHAR(7), -- hex color like #e84e23
    unit_id INTEGER REFERENCES units(id),
    amount REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_ingredient_or_tool CHECK (
        (ingredient_id IS NOT NULL AND tool_id IS NULL) OR
        (ingredient_id IS NULL AND tool_id IS NOT NULL)
    )
);

-- Indexes for performance
CREATE INDEX idx_recipe_transforms_recipe_id ON recipe_transforms(recipe_id);
CREATE INDEX idx_recipe_transform_io_recipe_id ON recipe_transform_io(recipe_id);
CREATE INDEX idx_recipe_transform_io_transform_id ON recipe_transform_io(recipe_transform_id);
CREATE INDEX idx_recipe_transform_io_pipe_uid ON recipe_transform_io(pipe_uid);

-- Insert some common units
INSERT INTO units (name) VALUES
    ('whole'), ('cups'), ('tablespoons'), ('teaspoons'),
    ('ounces'), ('pounds'), ('grams'), ('milliliters'),
    ('liters'), ('pinch'), ('pieces'), ('slices');
