# Stage 1: Build Next.js frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --only=production=false
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy backend source and install dependencies
COPY backend/ ./backend/
WORKDIR /app/backend
RUN uv sync --frozen --no-dev

# Copy frontend static export into backend's static serving dir
COPY --from=frontend-builder /app/frontend/out ./static/

# Create db directory for volume mount
RUN mkdir -p /app/db

WORKDIR /app/backend
EXPOSE 8000

ENV DB_PATH=/app/db/finally.db
ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
