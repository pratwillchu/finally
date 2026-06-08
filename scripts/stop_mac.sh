#!/usr/bin/env bash
set -e

CONTAINER_NAME="finally"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping FinAlly..."
    docker stop "$CONTAINER_NAME"
    docker rm "$CONTAINER_NAME"
    echo "Container stopped. Data volume preserved."
else
    echo "FinAlly is not running."
fi
