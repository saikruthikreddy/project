#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

# Start SSH service
echo "Starting SSH service..."
/usr/sbin/sshd

# Run your existing database initialization command
echo "Running Giani PKB database initialization..."
python -m giani_pkb.database.database_initialize

# Now, execute the main command passed to this script (your web server)
exec "$@"