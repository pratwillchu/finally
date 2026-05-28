# Market Data — Unified Python Interface

This document describes the unified market data interface used in FinAlly's backend. All price-producing code implements the same abstract contract so that downstream code (SSE streaming, portfolio valuation, trade execution) is completely agnostic to whether prices come from a live API or a simulator.

---

## Design Overview

```
MarketDataSource (ABC)          ← interface.py
├── SimulatorDataSource         ← simulator.py  (default, no API key needed)
└── MassiveDataSource           ← massive_client.py  (when MASSIVE_API_KEY is set)
        │
        ▼
   PriceCache (thread-safe)     ← cache.py
        │
        ├──→ SSE /api/stream/prices
        ├──→ Portfolio valuation
        └──→ Trade execution price lookup
```

**Key principle — Strategy Pattern**: the data source is selected once at startup by the factory. Everything downstream reads from `PriceCache` and never touches the source directly. Swapping simulator for live data (or vice versa) requires zero changes to consumers.

---

## Factory — Selecting the Right Source

```python
# backend/app/market/factory.py
from app.market import PriceCache, create_market_data_source

cache = PriceCache()
source = create_market_data_source(cache)
```

`create_market_data_source()` reads the `MASSIVE_API_KEY` environment variable:

| `MASSIVE_API_KEY` | Returns |
|-------------------|---------|
| Not set / empty string | `SimulatorDataSource(cache)` |
| Set to a non-empty value | `MassiveDataSource(api_key, cache)` |

No other configuration is needed. The `.env` file at the project root is loaded by the backend on startup.

---

## Abstract Interface — `MarketDataSource`

Defined in `backend/app/market/interface.py`.

```python
from abc import ABC, abstractmethod

class MarketDataSource(ABC):

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates. Called once at app startup."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task. Called on app shutdown."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. Takes effect on next update cycle."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker. Also removes it from the PriceCache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""
```

### Lifecycle Contract

```
start(tickers)          # One call. Starts background task.
    │
    ├── add_ticker()    # Zero or more times during runtime
    ├── remove_ticker() # Zero or more times during runtime
    │
stop()                  # One call. On app shutdown.
```

- `start()` is called exactly once with the initial watchlist from the database
- `stop()` is called exactly once when FastAPI shuts down (lifespan context)
- Both `add_ticker()` and `remove_ticker()` are safe to call at any time after `start()`
- Calling `start()` twice is undefined behavior — don't do it

---

## Price Cache — `PriceCache`

Defined in `backend/app/market/cache.py`. The single source of truth for current prices.

```python
from app.market import PriceCache

cache = PriceCache()
```

### Writing (Data Sources Only)

```python
# Called internally by SimulatorDataSource and MassiveDataSource
update = cache.update(ticker="AAPL", price=191.45)
update = cache.update(ticker="AAPL", price=191.45, timestamp=1716900000.0)
```

On first update for a ticker, `previous_price == price` (direction is `"flat"`).

### Reading (Downstream Code)

```python
# Get a single ticker
update: PriceUpdate | None = cache.get("AAPL")

# Get just the price float
price: float | None = cache.get_price("AAPL")

# Snapshot of all current prices
all_prices: dict[str, PriceUpdate] = cache.get_all()

# SSE change detection — increments on every update
version: int = cache.version
```

### Removing a Ticker

```python
cache.remove("GOOGL")  # Called by remove_ticker() on the data source
```

---

## Price Update — `PriceUpdate`

Defined in `backend/app/market/models.py`. Immutable frozen dataclass.

```python
from app.market import PriceUpdate
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `ticker` | str | Symbol, uppercase |
| `price` | float | Current price (rounded to 2 decimal places) |
| `previous_price` | float | Price before this update |
| `timestamp` | float | Unix seconds (float) |

### Computed Properties

```python
update.change          # float: price - previous_price
update.change_percent  # float: (change / previous_price) * 100
update.direction       # str: "up", "down", or "flat"
```

### Serialization

```python
update.to_dict()
# {
#   "ticker": "AAPL",
#   "price": 191.45,
#   "previous_price": 191.20,
#   "timestamp": 1716900000.0,
#   "change": 0.25,
#   "change_percent": 0.13,
#   "direction": "up"
# }
```

---

## SSE Streaming

The SSE endpoint is created from the price cache using a factory function:

```python
from app.market import create_stream_router

router = create_stream_router(price_cache)
app.include_router(router, prefix="/api")
# Exposes: GET /api/stream/prices
```

The stream uses **version-based change detection** — it only sends an SSE event when `cache.version` changes, which happens on every price update. The event payload is the `to_dict()` output for all tickers that changed since the last push.

---

## Complete Startup / Shutdown Pattern

This is how the interface is used in `backend/app/main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.market import PriceCache, create_market_data_source, create_stream_router
from app.db import get_watchlist_tickers  # Loads tickers from SQLite

price_cache = PriceCache()
market_source = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global market_source

    # Load watchlist from DB
    tickers = await get_watchlist_tickers()

    # Start the appropriate data source
    market_source = create_market_data_source(price_cache)
    await market_source.start(tickers)

    yield  # App is running

    # Shutdown
    if market_source:
        await market_source.stop()

app = FastAPI(lifespan=lifespan)

# Register SSE endpoint
stream_router = create_stream_router(price_cache)
app.include_router(stream_router, prefix="/api")
```

---

## Watchlist Integration

When the user adds or removes a ticker via the API, the data source must be updated:

```python
# POST /api/watchlist — add ticker
await market_source.add_ticker("PYPL")

# DELETE /api/watchlist/PYPL — remove ticker
await market_source.remove_ticker("PYPL")
```

Both operations are idempotent — adding a ticker already present, or removing one that doesn't exist, is a safe no-op.

---

## Thread Safety

`PriceCache` is protected by a `threading.Lock`. This matters because:

- The **Massive** data source runs the synchronous SDK in a thread pool via `asyncio.to_thread()` — writes come from a worker thread
- The **Simulator** runs as an asyncio task — writes come from the event loop
- SSE reads happen from async request handlers on the event loop

In all cases, `PriceCache` serializes access correctly. Callers do not need their own locking.

---

## Module Index

| Module | Class / Function | Purpose |
|--------|-----------------|---------|
| `app/market/models.py` | `PriceUpdate` | Immutable price snapshot dataclass |
| `app/market/cache.py` | `PriceCache` | Thread-safe in-memory price store |
| `app/market/interface.py` | `MarketDataSource` | Abstract base class |
| `app/market/simulator.py` | `SimulatorDataSource`, `GBMSimulator` | GBM price simulation |
| `app/market/massive_client.py` | `MassiveDataSource` | Polygon.io/Massive REST poller |
| `app/market/factory.py` | `create_market_data_source()` | Selects source from env var |
| `app/market/stream.py` | `create_stream_router()` | FastAPI SSE endpoint factory |
| `app/market/seed_prices.py` | `SEED_PRICES`, `TICKER_PARAMS`, etc. | Simulator starting state |
| `app/market/__init__.py` | — | Public re-exports |

### Public Imports

```python
from app.market import (
    PriceUpdate,
    PriceCache,
    MarketDataSource,
    create_market_data_source,
    create_stream_router,
)
```
