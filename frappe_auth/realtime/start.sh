#!/bin/bash
# Start the frappe_auth Socket.IO server

echo "Starting frappe_auth Socket.IO server..."

SOCKETIO_SERVER="$(dirname "$0")/socketio.js"

if [ ! -f "$SOCKETIO_SERVER" ]; then
    echo "Error: frappe_auth socketio.js not found at $SOCKETIO_SERVER"
    exit 1
fi

exec node "$SOCKETIO_SERVER"
