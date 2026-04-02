#!/bin/sh
set -e
# Bind mounts often arrive root-owned; app runs as non-root user monitor.
mkdir -p /app/data /app/logs
chown -R monitor:monitor /app/data /app/logs
exec runuser -u monitor -- "$@"
