"""Chat API router for FinAlly."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.database import get_db
from app.llm.chat_handler import handle_chat

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    """Send a message to the AI assistant and receive a structured response.

    Returns the assistant message plus any auto-executed trades and watchlist changes.
    """
    price_cache = request.app.state.price_cache
    market_source = getattr(request.app.state, "market_source", None)
    with get_db() as conn:
        result = handle_chat(req.message, price_cache, conn, market_source)
    return result
