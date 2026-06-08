"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/api/health")
async def health() -> dict:
    """Simple health check — returns 200 OK when the service is up."""
    return {"status": "ok"}
