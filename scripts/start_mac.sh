#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONTAINER_NAME="finally"
IMAGE_NAME="finally:latest"
BUILD_FLAG="${1:-}"

cd "$PROJECT_DIR"

# Check for .env file
if [ ! -f ".env" ]; then
    echo "No .env file found. Creating from .env.example..."
    cp .env.example .env
    echo "Edit .env to set your OPENROUTER_API_KEY before using AI chat."
fi

# Check if already running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "FinAlly is already running at http://localhost:8000"
    exit 0
fi

# Build if --build flag or image doesn't exist
if [ "$BUILD_FLAG" = "--build" ] || ! docker image inspect "$IMAGE_NAME" > /dev/null 2>&1; then
    echo "Building FinAlly..."
    docker build -t "$IMAGE_NAME" .
fi

# Remove stopped container if exists
docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1 || true

# Run
echo "Starting FinAlly..."
docker run -d \
    --name "$CONTAINER_NAME" \
    -v finally-data:/app/db \
    -p 8000:8000 \
    --env-file .env \
    "$IMAGE_NAME"

echo ""
echo "FinAlly is running!"
echo "   -> http://localhost:8000"
echo ""
echo "   To stop: ./scripts/stop_mac.sh"

# Open browser (optional -- comment out if unwanted)
sleep 1
if command -v open > /dev/null 2>&1; then
    open http://localhost:8000
fi
