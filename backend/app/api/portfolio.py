"""Portfolio API router and trade execution logic for FinAlly."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.database import get_db
from app.market import PriceCache

router = APIRouter(prefix="/api", tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: str  # "buy" or "sell"


def execute_trade(
    conn: sqlite3.Connection,
    ticker: str,
    side: str,
    quantity: float,
    price_cache: PriceCache,
) -> dict:
    """Execute a market order trade.

    Raises ValueError on validation failure (insufficient cash, insufficient shares).
    Returns trade record dict on success.
    """
    ticker = ticker.upper()
    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid side: {side!r}. Must be 'buy' or 'sell'.")
    if quantity <= 0:
        raise ValueError(f"Quantity must be positive, got {quantity}.")

    price = price_cache.get_price(ticker)
    if price is None:
        raise ValueError(f"No price available for {ticker!r}.")

    now = datetime.utcnow().isoformat()
    trade_id = str(uuid.uuid4())

    # Load cash balance
    row = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE id='default'"
    ).fetchone()
    if row is None:
        raise ValueError("User profile not found.")
    cash = row["cash_balance"]

    if side == "buy":
        cost = price * quantity
        if cost > cash:
            raise ValueError(
                f"Insufficient cash. Need ${cost:.2f}, have ${cash:.2f}."
            )
        # Deduct cash
        conn.execute(
            "UPDATE users_profile SET cash_balance=? WHERE id='default'",
            (cash - cost,),
        )
        # Upsert position
        existing = conn.execute(
            "SELECT quantity, avg_cost FROM positions WHERE user_id='default' AND ticker=?",
            (ticker,),
        ).fetchone()
        if existing:
            old_qty = existing["quantity"]
            old_cost = existing["avg_cost"]
            new_qty = old_qty + quantity
            new_avg = (old_qty * old_cost + quantity * price) / new_qty
            conn.execute(
                "UPDATE positions SET quantity=?, avg_cost=?, updated_at=? WHERE user_id='default' AND ticker=?",
                (new_qty, new_avg, now, ticker),
            )
        else:
            conn.execute(
                "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) VALUES (?, 'default', ?, ?, ?, ?)",
                (str(uuid.uuid4()), ticker, quantity, price, now),
            )

    else:  # sell
        existing = conn.execute(
            "SELECT quantity, avg_cost FROM positions WHERE user_id='default' AND ticker=?",
            (ticker,),
        ).fetchone()
        if not existing or existing["quantity"] < quantity:
            held = existing["quantity"] if existing else 0.0
            raise ValueError(
                f"Insufficient shares. Trying to sell {quantity}, holding {held}."
            )
        new_qty = existing["quantity"] - quantity
        proceeds = price * quantity
        conn.execute(
            "UPDATE users_profile SET cash_balance=? WHERE id='default'",
            (cash + proceeds,),
        )
        if new_qty == 0:
            conn.execute(
                "DELETE FROM positions WHERE user_id='default' AND ticker=?",
                (ticker,),
            )
        else:
            conn.execute(
                "UPDATE positions SET quantity=?, updated_at=? WHERE user_id='default' AND ticker=?",
                (new_qty, now, ticker),
            )

    # Record trade
    conn.execute(
        "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) VALUES (?, 'default', ?, ?, ?, ?, ?)",
        (trade_id, ticker, side, quantity, price, now),
    )

    # Record portfolio snapshot
    _record_snapshot(conn, price_cache, now)

    conn.commit()

    return {
        "id": trade_id,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "executed_at": now,
    }


def _record_snapshot(
    conn: sqlite3.Connection,
    price_cache: PriceCache,
    now: str | None = None,
) -> None:
    """Record a portfolio value snapshot."""
    if now is None:
        now = datetime.utcnow().isoformat()
    row = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE id='default'"
    ).fetchone()
    cash = row["cash_balance"] if row else 0.0

    positions = conn.execute(
        "SELECT ticker, quantity FROM positions WHERE user_id='default'"
    ).fetchall()

    total = cash
    for pos in positions:
        price = price_cache.get_price(pos["ticker"])
        if price:
            total += price * pos["quantity"]

    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, 'default', ?, ?)",
        (str(uuid.uuid4()), total, now),
    )


# ── FastAPI routes ──────────────────────────────────────────────────────────


@router.get("/portfolio")
async def get_portfolio(request: Request):
    """Return current positions, cash balance, total value, and unrealized P&L."""
    price_cache: PriceCache = request.app.state.price_cache
    with get_db() as conn:
        row = conn.execute(
            "SELECT cash_balance FROM users_profile WHERE id='default'"
        ).fetchone()
        cash = row["cash_balance"] if row else 10000.0

        positions_rows = conn.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions WHERE user_id='default'"
        ).fetchall()

    positions = []
    total_value = cash
    for pos in positions_rows:
        ticker = pos["ticker"]
        qty = pos["quantity"]
        avg_cost = pos["avg_cost"]
        current_price = price_cache.get_price(ticker) or avg_cost
        market_value = qty * current_price
        unrealized_pnl = (current_price - avg_cost) * qty
        pnl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost else 0.0
        total_value += market_value
        positions.append(
            {
                "ticker": ticker,
                "quantity": qty,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
                "pnl_pct": pnl_pct,
                "updated_at": pos["updated_at"],
            }
        )

    return {
        "cash_balance": cash,
        "total_value": total_value,
        "positions": positions,
    }


@router.post("/portfolio/trade")
async def trade(req: TradeRequest, request: Request):
    """Execute a market order trade."""
    price_cache: PriceCache = request.app.state.price_cache
    with get_db() as conn:
        try:
            result = execute_trade(conn, req.ticker, req.side, req.quantity, price_cache)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/portfolio/history")
async def portfolio_history():
    """Return portfolio value snapshots for the P&L chart."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT total_value, recorded_at FROM portfolio_snapshots WHERE user_id='default' ORDER BY recorded_at ASC"
        ).fetchall()
    return [{"total_value": r["total_value"], "recorded_at": r["recorded_at"]} for r in rows]
