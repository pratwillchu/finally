"""Pydantic schemas for LLM structured output."""

from __future__ import annotations

from pydantic import BaseModel


class TradeAction(BaseModel):
    ticker: str
    side: str  # "buy" or "sell"
    quantity: float


class WatchlistAction(BaseModel):
    ticker: str
    action: str  # "add" or "remove"


class ChatResponse(BaseModel):
    message: str
    trades: list[TradeAction] = []
    watchlist_changes: list[WatchlistAction] = []
