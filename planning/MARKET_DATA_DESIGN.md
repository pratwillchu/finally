# Market Data Backend — Detailed Design

Implementation-ready design for the FinAlly market data subsystem. Covers the unified interface, in-memory price cache, GBM simulator, Massive API client, SSE streaming endpoint, and FastAPI lifecycle integration. All code reflects the actual implementation in `backend/app/market/`.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [File Structure](#2-file-structure)
3. [Data Model — `models.py`](#3-data-model)
4. [Price Cache — `cache.py`](#4-price-cache)
5. [Abstract Interface — `interface.py`](#5-abstract-interface)
6. [Seed Prices & Ticker Parameters — `seed_prices.py`](#6-seed-prices--ticker-parameters)
7. [GBM Simulator — `simulator.py`](#7-gbm-simulator)
8. [Massive API Client — `massive_client.py`](#8-massive-api-client)
9. [Factory — `factory.py`](#9-factory)
10. [SSE Streaming Endpoint — `stream.py`](#10-sse-streaming-endpoint)
11. [FastAPI Lifecycle Integration](#11-fastapi-lifecycle-integration)
12. [Watchlist Coordination](#12-watchlist-coordination)
13. [Error Handling & Edge Cases](#13-error-handling--edge-cases)
14. [Testing Strategy](#14-testing-strategy)
15. [Configuration Reference](#15-configuration-reference)

---

## 1. Architecture Overview

```
MarketDataSource (ABC)          ← interface.py
├── SimulatorDataSource         ← simulator.py  (default, no API key needed)
└── MassiveDataSource           ← massive_client.py  (when MASSIVE_API_KEY is set)
        │
        ▼ writes to
   PriceCache (thread-safe)     ← cache.py
        │
        ├──→ SSE /api/stream/prices     (stream.py)
        ├──→ Portfolio valuation
        └──→ Trade execution price lookup
```

**Strategy Pattern**: the data source is selected once at startup by the factory (`factory.py`). Everything downstream reads from `PriceCache`. Swapping simulator for live data requires zero changes to consumers.

**Push model**: producers write into the cache on their own schedule; consumers poll the cache on their schedule. This decouples the 15-second Massive polling interval from the 500ms SSE push interval — the SSE endpoint always has something fresh to send because it reads the cache, not the API.

**Thread safety**: `PriceCache` uses `threading.Lock` (not `asyncio.Lock`) because the Massive client runs the synchronous SDK in `asyncio.to_thread()`, which operates in a real OS thread that cannot acquire an asyncio lock.

---

## 2. File Structure

```
backend/
  app/
    market/
      __init__.py          # Public re-exports
      models.py            # PriceUpdate frozen dataclass
      cache.py             # PriceCache — thread-safe in-memory store
      interface.py         # MarketDataSource ABC
      seed_prices.py       # Constants: seed prices, GBM params, correlation groups
      simulator.py         # GBMSimulator + SimulatorDataSource
      massive_client.py    # MassiveDataSource (Polygon.io/Massive REST poller)
      factory.py           # create_market_data_source() — reads MASSIVE_API_KEY
      stream.py            # FastAPI SSE endpoint factory
```

### Public imports

```python
from app.market import (
    PriceUpdate,
    PriceCache,
    MarketDataSource,
    create_market_data_source,
    create_stream_router,
)
```

Downstream code imports only from `app.market` — never from submodules directly.

---

## 3. Data Model

**File: `backend/app/market/models.py`**

`PriceUpdate` is the single data structure that flows out of the market data layer. Every consumer — SSE streaming, portfolio valuation, trade execution — works exclusively with this type.

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds

    @property
    def change(self) -> float:
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
        }
```

### Design notes

- **`frozen=True`**: immutable value objects, safe to share across async tasks without copying.
- **`slots=True`**: minor memory optimization — many instances are created per second.
- **Computed properties**: `change`, `change_percent`, `direction` are derived from stored fields so they can never be inconsistent.
- **`to_dict()`**: the single serialization point used by both the SSE endpoint and REST responses.

### Example output

```python
update = PriceUpdate(ticker="AAPL", price=191.45, previous_price=191.20)
update.to_dict()
# {
#   "ticker": "AAPL",
#   "price": 191.45,
#   "previous_price": 191.20,
#   "timestamp": 1716900000.0,
#   "change": 0.25,
#   "change_percent": 0.1307,
#   "direction": "up"
# }
```

---

## 4. Price Cache

**File: `backend/app/market/cache.py`**

The central data hub. Data sources write to it; SSE streaming and portfolio valuation read from it.

```python
from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker."""

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Bumped on every update; used for SSE change detection

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price. On first update, previous_price == price (direction='flat')."""
        with self._lock:
            ts = timestamp or time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price
            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        with self._lock:
            self._prices.pop(ticker, None)

    @property
    def version(self) -> int:
        return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

### Version counter for SSE

The SSE loop polls the cache every 500ms. Without a version counter it would send all prices every tick even if nothing changed (Massive only updates every 15s). The version counter lets the SSE loop skip sends when there are no new prices:

```python
last_version = -1
while True:
    current_version = price_cache.version
    if current_version != last_version:
        last_version = current_version
        yield format_sse(price_cache.get_all())
    await asyncio.sleep(0.5)
```

### Thread safety rationale

`threading.Lock` is used instead of `asyncio.Lock` because the Massive client's synchronous `get_snapshot_all()` runs in `asyncio.to_thread()` — a real OS thread pool — and `asyncio.Lock` cannot be acquired from a non-async context.

---

## 5. Abstract Interface

**File: `backend/app/market/interface.py`**

```python
from __future__ import annotations
from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Contract for all market data providers.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        await source.add_ticker("PYPL")      # at any time after start
        await source.remove_ticker("GOOGL")  # at any time after start
        await source.stop()                  # on app shutdown
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates. Called exactly once."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop background task and release resources. Safe to call multiple times."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker and evict it from PriceCache. No-op if absent."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the currently tracked ticker list."""
```

### Why the source writes to the cache instead of returning prices

The push model decouples timing. The simulator ticks at 500ms, Massive polls at 15s, but SSE always reads from the cache at its own 500ms cadence. The SSE layer has no knowledge of — and no dependency on — the active data source or its schedule.

---

## 6. Seed Prices & Ticker Parameters

**File: `backend/app/market/seed_prices.py`**

Constants only — no logic, no imports. Shared by both the simulator (starting prices, GBM parameters) and potentially by the Massive client (fallback prices on first launch before API responds).

```python
# Realistic starting prices for the default watchlist
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM": 195.00,
    "V": 280.00,
    "NFLX": 600.00,
}

# Per-ticker GBM parameters
# sigma: annualized volatility  (0.22 = 22%/year)
# mu:    annualized drift        (0.05 = 5%/year expected return)
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL":  {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT":  {"sigma": 0.20, "mu": 0.05},
    "AMZN":  {"sigma": 0.28, "mu": 0.05},
    "TSLA":  {"sigma": 0.50, "mu": 0.03},  # High vol, low drift
    "NVDA":  {"sigma": 0.40, "mu": 0.08},  # High vol, strong drift
    "META":  {"sigma": 0.30, "mu": 0.05},
    "JPM":   {"sigma": 0.18, "mu": 0.04},  # Low vol (bank)
    "V":     {"sigma": 0.17, "mu": 0.04},  # Low vol (payments)
    "NFLX":  {"sigma": 0.35, "mu": 0.05},
}

# Fallback for dynamically-added tickers not in the list above
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

# Sector groups — tickers in the same group move together
CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech":    {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

INTRA_TECH_CORR    = 0.6  # Tech stocks correlate 60%
INTRA_FINANCE_CORR = 0.5  # Finance stocks correlate 50%
CROSS_GROUP_CORR   = 0.3  # Cross-sector / unknown tickers
TSLA_CORR          = 0.3  # TSLA is in the tech set but behaves independently
```

Unknown tickers (dynamically added by the user) get a random seed price in the range `$50–$300` and `DEFAULT_PARAMS`.

---

## 7. GBM Simulator

**File: `backend/app/market/simulator.py`**

Two classes with a clear separation of concerns:

| Class | Layer | Dependencies |
|-------|-------|--------------|
| `GBMSimulator` | Pure math | `numpy`, stdlib only |
| `SimulatorDataSource` | Async adapter | Wraps `GBMSimulator`, writes to `PriceCache` |

### 7.1 Mathematical Model

Geometric Brownian Motion (GBM) — the same stochastic process underlying Black-Scholes:

```
S(t + dt) = S(t) × exp( (μ − σ²/2) × dt  +  σ × √dt × Z )
```

| Symbol | Meaning |
|--------|---------|
| `S(t)` | Current price |
| `μ` (mu) | Annualized drift (expected return, e.g. 0.05 = 5%/year) |
| `σ` (sigma) | Annualized volatility (e.g. 0.25 = 25%/year) |
| `dt` | Time step as fraction of a trading year |
| `Z` | Correlated standard normal draw |

`exp()` guarantees prices are always positive. The exponential (multiplicative) form matches real market returns — a 10% gain followed by a 10% loss does not return exactly to the start.

**Time step calculation** — each tick is 500ms:

```python
TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800
DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR   # ~8.48e-8
```

This tiny `dt` produces sub-cent moves per tick that accumulate naturally and look realistic over a session.

### 7.2 Correlated Moves — Cholesky Decomposition

Real stocks in the same sector tend to move together. The simulator replicates this:

1. Build an `n × n` correlation matrix `Σ` using sector-based pairwise correlations
2. Compute the Cholesky factor `L` such that `L @ Lᵀ = Σ`
3. Each tick: generate `n` independent normal draws `z_ind`
4. Apply `z_corr = L @ z_ind` → correlated draws
5. Use `z_corr[i]` as `Z` in the GBM formula for ticker `i`

The Cholesky matrix is rebuilt (`O(n²)`) whenever tickers are added or removed. With `n < 50` this is fast and happens infrequently.

### 7.3 GBMSimulator Code

```python
import math
import random
import numpy as np
from .seed_prices import (
    CORRELATION_GROUPS, CROSS_GROUP_CORR, DEFAULT_PARAMS,
    INTRA_FINANCE_CORR, INTRA_TECH_CORR, SEED_PRICES, TICKER_PARAMS, TSLA_CORR,
)


class GBMSimulator:

    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR  # ~8.48e-8

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None

        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def step(self) -> dict[str, float]:
        """Advance all tickers by one time step. Returns {ticker: new_price}."""
        n = len(self._tickers)
        if n == 0:
            return {}

        z_independent = np.random.standard_normal(n)
        z_correlated = self._cholesky @ z_independent if self._cholesky is not None else z_independent

        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            mu = self._params[ticker]["mu"]
            sigma = self._params[ticker]["sigma"]

            drift = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * math.sqrt(self._dt) * z_correlated[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            # Random shock: ~0.1% chance per tick per ticker
            # 10 tickers × 2 ticks/sec → ~1 event per 50 seconds across the watchlist
            if random.random() < self._event_prob:
                magnitude = random.uniform(0.02, 0.05)
                sign = random.choice([-1, 1])
                self._prices[ticker] *= 1 + magnitude * sign

            result[ticker] = round(self._prices[ticker], 2)

        return result

    def add_ticker(self, ticker: str) -> None:
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add without rebuilding Cholesky — for batch initialization."""
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker, random.uniform(50.0, 300.0))
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = rho
                corr[j, i] = rho
        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        tech = CORRELATION_GROUPS["tech"]
        finance = CORRELATION_GROUPS["finance"]
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR
        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR
```

### 7.4 SimulatorDataSource — Async Wrapper

```python
import asyncio
import logging
from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


class SimulatorDataSource(MarketDataSource):

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(tickers=tickers, event_probability=self._event_prob)
        # Seed cache immediately — SSE has data before the first loop tick
        for ticker in tickers:
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(tickers))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Simulator stopped")

    async def add_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.add_ticker(ticker)
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
            logger.info("Simulator: added %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)
        logger.info("Simulator: removed %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        while True:
            try:
                if self._sim:
                    prices = self._sim.step()
                    for ticker, price in prices.items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
```

### 7.5 Update Cycle

```
t = 0ms    GBMSimulator.step() called
           → n correlated GBM moves (Cholesky)
           → optional random shocks (~0.1% each)
           → returns {ticker: price}
           Cache updated n times → version bumps n times

t = 500ms  asyncio.sleep() completes → next step()
```

### 7.6 Adding a Ticker at Runtime

```python
await simulator_source.add_ticker("PYPL")
# Internal sequence:
# 1. GBMSimulator._add_ticker_internal("PYPL")
#    - seed price: SEED_PRICES.get("PYPL", random.uniform(50, 300))
#    - params: DEFAULT_PARAMS (unknown ticker)
# 2. _rebuild_cholesky() — O(n²), fast for n < 50
# 3. cache.update("PYPL", price) — price available immediately, no wait for next tick
```

---

## 8. Massive API Client

**File: `backend/app/market/massive_client.py`**

Polls the Massive (formerly Polygon.io) REST API batch snapshot endpoint on a configurable interval. The synchronous Massive SDK runs in `asyncio.to_thread()` to avoid blocking the event loop.

```python
from __future__ import annotations

import asyncio
import logging

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


class MassiveDataSource(MarketDataSource):
    """Polls Massive (Polygon.io) batch snapshot endpoint.

    Rate limits:
      Free / Starter:  5 req/min  → poll every 15s (default)
      Paid tiers:      higher     → poll every 2–5s
    """

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = list(tickers)
        # Immediate first poll — cache has data before the loop starts
        await self._poll_once()
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info("Massive poller started: %d tickers, %.1fs interval", len(tickers), self._interval)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            logger.info("Massive: added %s (appears on next poll)", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)
        logger.info("Massive: removed %s", ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def _poll_loop(self) -> None:
        """Interval loop. First poll already happened in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        if not self._tickers or not self._client:
            return
        try:
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
            processed = 0
            for snap in snapshots:
                try:
                    price = snap.last_trade.price
                    # Massive snapshot timestamps are Unix milliseconds
                    timestamp = snap.last_trade.timestamp / 1000.0
                    self._cache.update(ticker=snap.ticker, price=price, timestamp=timestamp)
                    processed += 1
                except (AttributeError, TypeError) as e:
                    logger.warning("Skipping snapshot for %s: %s", getattr(snap, "ticker", "???"), e)
            logger.debug("Massive poll: updated %d/%d tickers", processed, len(self._tickers))
        except Exception as e:
            logger.error("Massive poll failed: %s", e)
            # Don't re-raise — retries automatically on next interval

    def _fetch_snapshots(self) -> list:
        """Synchronous SDK call — runs inside asyncio.to_thread()."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=self._tickers,
        )
```

### Massive API snapshot format

The batch snapshot endpoint `GET /v2/snapshot/locale/us/markets/stocks/tickers` returns one object per ticker:

```
snap.ticker                    → "AAPL"
snap.last_trade.price          → 191.45
snap.last_trade.timestamp      → 1716900000000  (Unix milliseconds)
snap.day.o / .h / .l / .c     → today's OHLC
snap.todaysChangePerc          → % change today
```

### Timestamp conversion

| Endpoint | Unit | Convert to seconds |
|----------|------|--------------------|
| `last_trade.timestamp` | Milliseconds | `/ 1000.0` |
| `last_trade` from `get_last_trade()` | Nanoseconds | `/ 1_000_000_000` |
| Aggregates `.t` | Milliseconds | `/ 1000.0` |

### Error handling table

| Error | Behavior |
|-------|----------|
| 401 Unauthorized | Logged as error; poller keeps retrying (fix `.env` and restart) |
| 429 Rate Limited | Logged as error; retries after `poll_interval` seconds |
| Network timeout | Logged as error; retries automatically |
| Malformed snapshot | Individual ticker skipped with warning; others still processed |
| All tickers fail | Cache retains last-known prices; SSE streams stale data |

### Difference from simulator on `add_ticker`

Unlike the simulator, the Massive client does **not** seed the cache immediately when a ticker is added — it must wait for the next poll cycle (up to 15 seconds on free tier). The API route should handle the potential `None` price:

```python
price = price_cache.get_price(ticker)
# May be None for the first ~15s after adding via Massive source
```

---

## 9. Factory

**File: `backend/app/market/factory.py`**

```python
from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Select simulator or Massive based on MASSIVE_API_KEY environment variable.

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        logger.info("Market data source: Massive API (real data)")
        return MassiveDataSource(api_key=api_key, price_cache=price_cache)
    else:
        logger.info("Market data source: GBM Simulator")
        return SimulatorDataSource(price_cache=price_cache)
```

### Selection logic

| `MASSIVE_API_KEY` env var | Returns |
|---------------------------|---------|
| Not set or empty string | `SimulatorDataSource` |
| Set to a non-empty value | `MassiveDataSource` |

### Typical startup

```python
price_cache = PriceCache()
source = create_market_data_source(price_cache)
await source.start(["AAPL", "GOOGL", "MSFT", ...])
```

---

## 10. SSE Streaming Endpoint

**File: `backend/app/market/stream.py`**

The SSE endpoint holds open a long-lived HTTP connection and pushes price updates as `text/event-stream`. Uses a factory function to inject the `PriceCache` without globals.

```python
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stream", tags=["streaming"])


def create_stream_router(price_cache: PriceCache) -> APIRouter:
    """Create the SSE router with an injected PriceCache reference."""

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
            },
        )

    return router


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
    interval: float = 0.5,
) -> AsyncGenerator[str, None]:
    """Yield SSE events every ~500ms. Stops on client disconnect."""
    yield "retry: 1000\n\n"  # Tell browser to reconnect after 1s if dropped

    last_version = -1
    client_ip = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client_ip)

    try:
        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected: %s", client_ip)
                break

            current_version = price_cache.version
            if current_version != last_version:
                last_version = current_version
                prices = price_cache.get_all()
                if prices:
                    data = {ticker: update.to_dict() for ticker, update in prices.items()}
                    yield f"data: {json.dumps(data)}\n\n"

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for: %s", client_ip)
```

### SSE wire format

Each event the browser receives:

```
retry: 1000

data: {"AAPL":{"ticker":"AAPL","price":190.50,"previous_price":190.42,"timestamp":1707580800.5,"change":0.08,"change_percent":0.042,"direction":"up"},"GOOGL":{...},...}

```

(Blank line after `data:` line terminates the event.)

### Frontend consumption

```javascript
const es = new EventSource('/api/stream/prices');

es.onmessage = (event) => {
    const prices = JSON.parse(event.data);
    // prices: { "AAPL": { ticker, price, previous_price, change, change_percent, direction, timestamp }, ... }
    for (const [ticker, update] of Object.entries(prices)) {
        updateWatchlistRow(ticker, update);
        if (update.direction !== 'flat') {
            flashPrice(ticker, update.direction);  // CSS animation
        }
    }
};

es.onerror = () => {
    // EventSource automatically reconnects after the retry: 1000 delay
    setConnectionStatus('reconnecting');
};
```

### Why poll-and-push instead of event-driven

The SSE loop polls the cache on a fixed interval rather than being notified by the data source. This gives the frontend evenly-spaced updates regardless of the data source's schedule. Regular timing is important for the sparkline charts, which accumulate values by time.

---

## 11. FastAPI Lifecycle Integration

**File: `backend/app/main.py`**

Market data is started and stopped with the FastAPI app via the `lifespan` context manager pattern.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends

from app.market.cache import PriceCache
from app.market.factory import create_market_data_source
from app.market.interface import MarketDataSource
from app.market.stream import create_stream_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    price_cache = PriceCache()
    app.state.price_cache = price_cache

    source = create_market_data_source(price_cache)
    app.state.market_source = source

    initial_tickers = await load_watchlist_tickers()  # read from SQLite
    await source.start(initial_tickers)

    stream_router = create_stream_router(price_cache)
    app.include_router(stream_router)

    yield  # App is running

    # Shutdown
    await source.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)


# Dependency functions for injection into route handlers
def get_price_cache() -> PriceCache:
    return app.state.price_cache


def get_market_source() -> MarketDataSource:
    return app.state.market_source
```

### Injecting into route handlers

```python
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api")


@router.post("/portfolio/trade")
async def execute_trade(
    trade: TradeRequest,
    price_cache: PriceCache = Depends(get_price_cache),
):
    current_price = price_cache.get_price(trade.ticker)
    if current_price is None:
        raise HTTPException(400, f"No price available for {trade.ticker}. Try again in a moment.")
    # ... execute trade at current_price ...


@router.post("/watchlist")
async def add_to_watchlist(
    payload: WatchlistAdd,
    source: MarketDataSource = Depends(get_market_source),
    price_cache: PriceCache = Depends(get_price_cache),
):
    await db.insert_watchlist_entry(payload.ticker)
    await source.add_ticker(payload.ticker)
    price = price_cache.get_price(payload.ticker)  # May be None if Massive hasn't polled yet
    return {"ticker": payload.ticker, "price": price}


@router.delete("/watchlist/{ticker}")
async def remove_from_watchlist(
    ticker: str,
    source: MarketDataSource = Depends(get_market_source),
):
    await db.delete_watchlist_entry(ticker)
    position = await db.get_position(ticker)
    # Keep tracking if user still holds shares — portfolio valuation needs the price
    if position is None or position.quantity == 0:
        await source.remove_ticker(ticker)
    return {"status": "ok"}
```

---

## 12. Watchlist Coordination

Both add and remove operations are **idempotent** — calling them multiple times is safe.

### Adding a ticker

```
POST /api/watchlist {"ticker": "PYPL"}
  → Format validation: 1–5 uppercase alphanumeric chars
  → (Massive mode only): attempt price lookup to confirm ticker exists
  → Insert row into watchlist table
  → await source.add_ticker("PYPL")
      Simulator: add to GBMSimulator, rebuild Cholesky, seed cache immediately
      Massive:   append to ticker list; price available on next poll (~15s)
  → Return {ticker, price}
```

### Removing a ticker

```
DELETE /api/watchlist/PYPL
  → Delete row from watchlist table
  → Check if user has an open position in PYPL
  → If no position (or zero quantity): await source.remove_ticker("PYPL")
      Both implementations: remove from cache, stop tracking
  → Return {status: "ok"}
```

### Position-aware removal

If the user removes a ticker from the watchlist while holding shares, the data source must keep tracking it for accurate portfolio valuation:

```python
position = await db.get_position(ticker)
if position is None or position.quantity == 0:
    await source.remove_ticker(ticker)
# If they still hold shares: ticker stays tracked, price keeps updating
```

---

## 13. Error Handling & Edge Cases

### Empty watchlist at startup

Both data sources accept an empty `tickers` list in `start()`. The simulator produces no prices, the Massive poller skips its API call. The SSE endpoint emits empty events. When the user adds the first ticker, tracking begins immediately.

### Price cache miss during trade execution

```python
price = price_cache.get_price(ticker)
if price is None:
    raise HTTPException(
        status_code=400,
        detail=f"Price not yet available for {ticker}. Please wait a moment and try again.",
    )
```

The simulator avoids this via immediate seeding in `add_ticker()`. The Massive client may have a brief gap of up to `poll_interval` seconds on a newly-added ticker.

### Invalid Massive API key

First poll fails with HTTP 401. The poller logs the error and keeps retrying. SSE streams empty or stale data. The connection status indicator shows connected (SSE is working) but prices don't update. Fix: correct the API key and restart the container.

### Massive rate limiting (HTTP 429)

The poll loop logs the error and waits `poll_interval` seconds before retrying. At the default 15-second interval on the free tier (5 req/min), rate limiting should never occur for a 10-ticker watchlist.

### Duplicate add / nonexistent remove

Both `add_ticker()` and `remove_ticker()` are no-ops if the ticker is already present or absent respectively. No locking required around callers.

### Simulator floating-point stability

GBM with tiny `dt` is numerically stable because:
- `math.exp(drift + diffusion)` is always positive — prices can never go negative
- Prices are `round()`ed to 2 decimal places in `GBMSimulator.step()`
- No accumulation of floating-point error because each step multiplies the current price (not an accumulated sum)

---

## 14. Testing Strategy

### Unit tests for GBMSimulator

```python
import pytest
from app.market.simulator import GBMSimulator
from app.market.seed_prices import SEED_PRICES


class TestGBMSimulator:

    def test_step_returns_all_tickers(self):
        sim = GBMSimulator(["AAPL", "GOOGL"])
        assert set(sim.step().keys()) == {"AAPL", "GOOGL"}

    def test_prices_are_always_positive(self):
        sim = GBMSimulator(["AAPL"])
        for _ in range(10_000):
            assert sim.step()["AAPL"] > 0

    def test_initial_prices_match_seeds(self):
        sim = GBMSimulator(["AAPL"])
        assert sim.get_price("AAPL") == SEED_PRICES["AAPL"]

    def test_add_ticker_appears_in_step(self):
        sim = GBMSimulator(["AAPL"])
        sim.add_ticker("TSLA")
        assert "TSLA" in sim.step()

    def test_remove_ticker_absent_from_step(self):
        sim = GBMSimulator(["AAPL", "GOOGL"])
        sim.remove_ticker("GOOGL")
        result = sim.step()
        assert "GOOGL" not in result
        assert "AAPL" in result

    def test_add_duplicate_is_noop(self):
        sim = GBMSimulator(["AAPL"])
        sim.add_ticker("AAPL")
        assert len(sim._tickers) == 1

    def test_remove_nonexistent_is_noop(self):
        sim = GBMSimulator(["AAPL"])
        sim.remove_ticker("ZZZZ")  # Must not raise

    def test_unknown_ticker_gets_random_seed(self):
        sim = GBMSimulator(["ZZZZ"])
        assert 50.0 <= sim.get_price("ZZZZ") <= 300.0

    def test_empty_step(self):
        assert GBMSimulator([]).step() == {}

    def test_cholesky_none_for_single_ticker(self):
        sim = GBMSimulator(["AAPL"])
        assert sim._cholesky is None

    def test_cholesky_built_for_multiple_tickers(self):
        sim = GBMSimulator(["AAPL", "GOOGL"])
        assert sim._cholesky is not None
```

### Unit tests for PriceCache

```python
from app.market.cache import PriceCache


class TestPriceCache:

    def test_update_and_get(self):
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.price == 190.50
        assert cache.get("AAPL") == update

    def test_first_update_is_flat(self):
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.direction == "flat"
        assert update.previous_price == update.price

    def test_direction_up(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        assert cache.update("AAPL", 191.00).direction == "up"

    def test_direction_down(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        assert cache.update("AAPL", 189.00).direction == "down"

    def test_remove_evicts_ticker(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.remove("AAPL")
        assert cache.get("AAPL") is None

    def test_version_increments_on_update(self):
        cache = PriceCache()
        v0 = cache.version
        cache.update("AAPL", 190.00)
        assert cache.version == v0 + 1
        cache.update("AAPL", 191.00)
        assert cache.version == v0 + 2

    def test_get_price_convenience(self):
        cache = PriceCache()
        cache.update("AAPL", 190.50)
        assert cache.get_price("AAPL") == 190.50
        assert cache.get_price("UNKNOWN") is None

    def test_get_all_returns_copy(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        all_prices = cache.get_all()
        assert "AAPL" in all_prices
        # Modifying the returned dict does not affect the cache
        all_prices["FAKE"] = None
        assert "FAKE" not in cache.get_all()
```

### Integration tests for SimulatorDataSource

```python
import asyncio
import pytest
from app.market.cache import PriceCache
from app.market.simulator import SimulatorDataSource


@pytest.mark.asyncio
class TestSimulatorDataSource:

    async def test_start_populates_cache_immediately(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache)
        await source.start(["AAPL", "GOOGL"])
        # Cache seeded before first loop tick
        assert cache.get("AAPL") is not None
        assert cache.get("GOOGL") is not None
        await source.stop()

    async def test_stop_is_idempotent(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache)
        await source.start(["AAPL"])
        await source.stop()
        await source.stop()  # Must not raise

    async def test_add_and_remove_ticker(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache)
        await source.start(["AAPL"])

        await source.add_ticker("TSLA")
        assert "TSLA" in source.get_tickers()
        assert cache.get("TSLA") is not None  # Seeded immediately

        await source.remove_ticker("TSLA")
        assert "TSLA" not in source.get_tickers()
        assert cache.get("TSLA") is None  # Evicted from cache

        await source.stop()
```

### Unit tests for MassiveDataSource (mocked)

```python
from unittest.mock import MagicMock, patch
import pytest
from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource


def make_snapshot(ticker, price, ts_ms=1707580800000):
    snap = MagicMock()
    snap.ticker = ticker
    snap.last_trade.price = price
    snap.last_trade.timestamp = ts_ms
    return snap


@pytest.mark.asyncio
class TestMassiveDataSource:

    async def test_poll_updates_cache(self):
        cache = PriceCache()
        source = MassiveDataSource(api_key="test", price_cache=cache, poll_interval=60.0)
        source._tickers = ["AAPL"]

        with patch.object(source, "_fetch_snapshots", return_value=[make_snapshot("AAPL", 190.50)]):
            await source._poll_once()

        assert cache.get_price("AAPL") == 190.50

    async def test_malformed_snapshot_is_skipped(self):
        cache = PriceCache()
        source = MassiveDataSource(api_key="test", price_cache=cache, poll_interval=60.0)
        source._tickers = ["AAPL", "BAD"]

        bad = MagicMock()
        bad.ticker = "BAD"
        bad.last_trade = None  # AttributeError on .price

        with patch.object(source, "_fetch_snapshots",
                          return_value=[make_snapshot("AAPL", 190.50), bad]):
            await source._poll_once()

        assert cache.get_price("AAPL") == 190.50
        assert cache.get_price("BAD") is None

    async def test_api_error_does_not_crash(self):
        cache = PriceCache()
        source = MassiveDataSource(api_key="test", price_cache=cache, poll_interval=60.0)
        source._tickers = ["AAPL"]

        with patch.object(source, "_fetch_snapshots", side_effect=Exception("network error")):
            await source._poll_once()  # Must not raise

    async def test_add_and_remove_ticker(self):
        cache = PriceCache()
        source = MassiveDataSource(api_key="test", price_cache=cache)
        source._tickers = ["AAPL"]

        await source.add_ticker("TSLA")
        assert "TSLA" in source.get_tickers()

        await source.remove_ticker("TSLA")
        assert "TSLA" not in source.get_tickers()
```

### Running the tests

```bash
cd backend
uv run --extra dev pytest -v                    # All tests
uv run --extra dev pytest tests/market/ -v      # Market data only
uv run --extra dev pytest --cov=app/market      # With coverage
```

---

## 15. Configuration Reference

All tunable parameters and their defaults:

| Parameter | Location | Default | Description |
|-----------|----------|---------|-------------|
| `MASSIVE_API_KEY` | Environment variable | `""` | If non-empty, use Massive API; else use simulator |
| `update_interval` | `SimulatorDataSource.__init__` | `0.5` s | Time between simulator ticks |
| `poll_interval` | `MassiveDataSource.__init__` | `15.0` s | Time between Massive API polls |
| `event_probability` | `GBMSimulator.__init__` | `0.001` | Shock event probability per ticker per tick |
| `dt` | `GBMSimulator.__init__` | `~8.48e-8` | GBM time step (fraction of a trading year) |
| SSE push interval | `_generate_events()` | `0.5` s | Time between SSE pushes to the client |
| SSE retry directive | `_generate_events()` | `1000` ms | Browser EventSource reconnection delay |

### Rate limits by Massive plan

| Plan | Rate Limit | Recommended `poll_interval` |
|------|-----------|------------------------------|
| Free / Basic | 5 req/min | 15s (stays safely within limit) |
| Starter | 5 req/min | 15s |
| Developer | Higher | 5–10s |
| Advanced | Higher | 2–5s |
| Business | Unlimited | 1–2s |

### Demo without the full app

```bash
cd backend
uv run market_data_demo.py
```

Displays a live Rich terminal dashboard with all 10 tickers, color-coded direction arrows, sparkline mini-charts, and a log of random shock events. Runs for 60 seconds or until Ctrl+C. Useful for tuning GBM parameters visually.
