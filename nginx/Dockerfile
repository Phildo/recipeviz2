FROM nginx:alpine

# Remove default config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom config
COPY nginx.conf /etc/nginx/nginx.conf

# Copy frontend files
COPY ../frontend/ /usr/share/nginx/html/

EXPOSE 80
