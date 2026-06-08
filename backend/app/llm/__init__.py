"""LLM integration for FinAlly.

Public API:
    ChatResponse       - Structured output schema
    TradeAction        - Trade action schema
    WatchlistAction    - Watchlist action schema
    handle_chat        - Main chat handler function
"""

from .chat_handler import handle_chat
from .schemas import ChatResponse, TradeAction, WatchlistAction

__all__ = ["ChatResponse", "TradeAction", "WatchlistAction", "handle_chat"]
