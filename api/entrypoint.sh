#!/bin/sh
set -e

echo "Applying Alembic database migrations..."
alembic upgrade head
echo "Database migrations applied successfully."

echo "Starting API application..."
exec "$@"

