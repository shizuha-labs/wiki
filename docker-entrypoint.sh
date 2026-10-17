#!/bin/bash
set -e

# Wait for database to be ready
echo "Waiting for PostgreSQL..."
while ! nc -z ${POSTGRES_HOST:-shizuha-db} ${POSTGRES_PORT:-5432}; do
  sleep 1
done
echo "PostgreSQL is ready!"

# Install shared packages if mounted
if [ -d /packages/shizuha-auth ]; then
    echo "Installing shizuha-auth package..."
    pip install -e /packages/shizuha-auth --quiet
fi

if [ -d /packages/shizuha-storage ]; then
    echo "Installing shizuha-storage package..."
    pip install -e /packages/shizuha-storage --quiet
fi

# Create database if it doesn't exist
echo "Ensuring database exists..."
python manage.py createdb || true

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Administrator accounts are explicit operator actions. To create a local
# Django administrator, run manage.py createsuperuser interactively.

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Setup complete. Starting services with supervisord..."
exec supervisord -c /app/supervisord.conf

# PLAT-10781: rebuild-trigger after python:3.10-slim base resnapshot (no behavioral change).
