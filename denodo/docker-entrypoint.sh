#!/bin/bash
# Denodo Docker Entrypoint
# Starts Denodo server and runs initialization in background

set -e

echo "=========================================="
echo "Starting Denodo Virtual DataPort"
echo "=========================================="

# Start initialization in background after a delay
# This allows Denodo to start first
(
    sleep 30
    /opt/denodo/init-startup.sh
) > /var/log/denodo-init.log 2>&1 &

# Start Denodo using the original entrypoint
# The CMD from Dockerfile will be passed as arguments
exec /opt/denodo/bin/entrypoint.sh "$@"
