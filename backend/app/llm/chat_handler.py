"""Chat handler — orchestrates portfolio context, LLM call, and action execution."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime

from app.llm.client import call_llm
from app.llm.schemas import ChatResponse
from app.market import PriceCache


def _build_system_prompt(conn: sqlite3.Connection, price_cache: PriceCache) -> str:
    """Build the system prompt with current portfolio context."""
    # Cash balance
    row = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE id='default'"
    ).fetchone()
    cash = row["cash_balance"] if row else 0.0

    # Positions with P&L
    positions_rows = conn.execute(
        "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id='default'"
    ).fetchall()

    total_value = cash
    position_lines: list[str] = []
    for pos in positions_rows:
        ticker = pos["ticker"]
        qty = pos["quantity"]
        avg_cost = pos["avg_cost"]
        price = price_cache.get_price(ticker) or avg_cost
        pnl = (price - avg_cost) * qty
        pnl_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost else 0.0
        total_value += price * qty
        position_lines.append(
            f"  {ticker}: {qty} shares @ ${avg_cost:.2f} avg, "
            f"current ${price:.2f}, P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)"
        )

    positions_text = "\n".join(position_lines) if position_lines else "  (no positions)"

    # Watchlist with live prices
    watchlist_rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id='default' ORDER BY added_at ASC"
    ).fetchall()
    watchlist_lines: list[str] = []
    for w in watchlist_rows:
        ticker = w["ticker"]
        update = price_cache.get(ticker)
        if update:
            watchlist_lines.append(
                f"  {ticker}: ${update.price:.2f} ({update.change_percent:+.2f}%)"
            )
        else:
            watchlist_lines.append(f"  {ticker}: (price unavailable)")
    watchlist_text = "\n".join(watchlist_lines) if watchlist_lines else "  (empty watchlist)"

    return f"""You are FinAlly, an AI trading assistant. Be concise and data-driven.
Always respond with valid JSON matching the required schema.

Portfolio Context:
- Cash Balance: ${cash:,.2f}
- Total Portfolio Value: ${total_value:,.2f} (including positions)
- Positions:
{positions_text}
- Watchlist prices:
{watchlist_text}

You can execute trades (buy/sell) and manage the watchlist.
When asked to trade, always confirm the action in your message."""


def handle_chat(
    user_message: str,
    price_cache: PriceCache,
    conn: sqlite3.Connection,
    market_source=None,
) -> dict:
    """Process a user chat message end-to-end.

    Steps:
      1. Build portfolio context for system prompt
      2. Load last 20 messages from DB
      3. Call LLM (or mock)
      4. Execute trades
      5. Execute watchlist changes
      6. Save messages to DB
      7. Return response dict
    """
    # ── 1. Build system prompt ──────────────────────────────────────────────
    system_prompt = _build_system_prompt(conn, price_cache)

    # ── 2. Load conversation history ────────────────────────────────────────
    rows = conn.execute(
        "SELECT role, content FROM chat_messages WHERE user_id='default' "
        "ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    history = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    # ── 3. Build messages and call LLM ──────────────────────────────────────
    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]
    llm_response: ChatResponse = call_llm(messages)

    # ── 4. Execute trades ───────────────────────────────────────────────────
    from app.api.portfolio import execute_trade  # noqa: PLC0415 (avoid circular import at module level)

    errors: list[str] = []
    for trade in llm_response.trades:
        try:
            execute_trade(conn, trade.ticker, trade.side, trade.quantity, price_cache)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    # ── 5. Execute watchlist changes ────────────────────────────────────────
    now = datetime.utcnow().isoformat()
    for change in llm_response.watchlist_changes:
        ticker_upper = change.ticker.upper()
        if change.action == "add":
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) "
                    "VALUES (?, 'default', ?, ?)",
                    (str(uuid.uuid4()), ticker_upper, now),
                )
                if market_source is not None:
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(market_source.add_ticker(ticker_upper))
                    except RuntimeError:
                        pass  # No event loop — skip async ticker add
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        elif change.action == "remove":
            try:
                conn.execute(
                    "DELETE FROM watchlist WHERE user_id='default' AND ticker=?",
                    (ticker_upper,),
                )
                if market_source is not None:
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(market_source.remove_ticker(ticker_upper))
                    except RuntimeError:
                        pass
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

    # ── 6. Save to chat_messages ────────────────────────────────────────────
    conn.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
        "VALUES (?, 'default', 'user', ?, NULL, ?)",
        (str(uuid.uuid4()), user_message, now),
    )
    actions = {
        "trades": [t.model_dump() for t in llm_response.trades],
        "watchlist_changes": [w.model_dump() for w in llm_response.watchlist_changes],
        "errors": errors,
    }
    conn.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
        "VALUES (?, 'default', 'assistant', ?, ?, ?)",
        (str(uuid.uuid4()), llm_response.message, json.dumps(actions), now),
    )
    conn.commit()

    # ── 7. Return response dict ─────────────────────────────────────────────
    return {
        "message": llm_response.message,
        "trades": [t.model_dump() for t in llm_response.trades],
        "watchlist_changes": [w.model_dump() for w in llm_response.watchlist_changes],
        "errors": errors,
    }
