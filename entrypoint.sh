#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

# Start SSH service
echo "Starting SSH service..."
/usr/sbin/sshd

# Run database migrations
echo "Running database migrations..."
python manage.py apply --revision head

# If migrations fail, try to initialize (for new deployments)
if [ $? -ne 0 ]; then
    echo "Migrations failed, checking if this is a new deployment..."
    python manage.py init-alembic 2>/dev/null || true
    python manage.py apply --revision head 2>/dev/null || true
fi

# Execute the main command
exec "$@"
