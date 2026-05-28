# Market Simulator — Approach and Code Structure

This document describes the GBM-based market price simulator used by FinAlly when no `MASSIVE_API_KEY` is set. The simulator is the default mode and requires no external dependencies or API keys.

---

## Why a Simulator?

The simulator serves several purposes:

1. **Zero dependencies** — works offline, no API key, no rate limits, no cost
2. **Determinism in tests** — reproducible price movements with fixed seeds
3. **Drama** — occasional random shocks create interesting visual activity
4. **Correctness** — prices follow the same statistical process as real markets (GBM), so portfolio math is realistic

---

## Mathematical Model — Geometric Brownian Motion (GBM)

The simulator uses **Geometric Brownian Motion**, the same stochastic process underlying the Black-Scholes options pricing model.

### Formula

```
S(t + dt) = S(t) × exp( (μ − σ²/2) × dt  +  σ × √dt × Z )
```

Where:
| Symbol | Name | Meaning |
|--------|------|---------|
| `S(t)` | Current price | Price at time `t` |
| `μ` (mu) | Drift | Annualized expected return (e.g., 0.05 = 5%/year) |
| `σ` (sigma) | Volatility | Annualized standard deviation (e.g., 0.25 = 25%/year) |
| `dt` | Time step | Fraction of a trading year per tick |
| `Z` | Random draw | Standard normal variable (correlated across tickers) |

### Why exp() and not additive?

Using the exponential form ensures prices can never go negative (a core GBM property) and models the **multiplicative** nature of returns — a 10% gain followed by a 10% loss does not return to the starting point.

### Time Step Scaling

Each tick is 500ms. The time step `dt` is expressed as a fraction of one trading year:

```
Trading seconds/year = 252 days × 6.5 hours/day × 3600 sec/hour = 5,896,800 sec
dt = 0.5 / 5,896,800 ≈ 8.48 × 10⁻⁸
```

This tiny `dt` produces sub-cent moves per tick that accumulate naturally and realistically over a session. There is no need to artificially scale prices — the math self-corrects.

---

## Correlated Moves — Cholesky Decomposition

Real stocks in the same sector tend to move together. The simulator replicates this using a **Cholesky decomposition** of a correlation matrix.

### Correlation Groups

```python
CORRELATION_GROUPS = {
    "tech":    {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

INTRA_TECH_CORR    = 0.6   # Tech stocks correlate at 60%
INTRA_FINANCE_CORR = 0.5   # Finance stocks correlate at 50%
CROSS_GROUP_CORR   = 0.3   # Cross-sector (including unknowns)
TSLA_CORR          = 0.3   # TSLA: in tech group but does its own thing
```

### How Cholesky Works

1. Build an `n × n` correlation matrix `Σ` where `Σ[i,j]` is the pairwise correlation between ticker `i` and ticker `j`
2. Compute the Cholesky factor `L = cholesky(Σ)` — a lower-triangular matrix such that `L @ Lᵀ = Σ`
3. Each tick: generate `n` independent standard normal draws `z_ind`
4. Apply `z_corr = L @ z_ind` to get correlated draws
5. Use `z_corr[i]` as the `Z` term in the GBM formula for ticker `i`

```python
# In GBMSimulator.step()
z_independent = np.random.standard_normal(n)   # n uncorrelated draws
z_correlated  = self._cholesky @ z_independent  # n correlated draws
```

The Cholesky matrix is rebuilt whenever tickers are added or removed. With `n < 50` this is fast (O(n²)) and happens rarely.

---

## Random Shock Events

To add visual drama (sudden price spikes/drops visible in the UI), the simulator applies random shocks:

```python
# Per tick, per ticker: 0.1% chance of a 2–5% move
if random.random() < 0.001:
    magnitude = random.uniform(0.02, 0.05)
    direction = random.choice([-1, 1])
    price *= (1 + magnitude * direction)
```

With 10 tickers at 2 ticks/second: expected frequency ≈ one event every ~50 seconds across the whole watchlist. This keeps the UI lively without being chaotic.

---

## Seed Prices and Parameters

Every ticker starts from a realistic seed price. Per-ticker GBM parameters control how volatile and directional each stock behaves:

```python
SEED_PRICES = {
    "AAPL":  190.00,
    "GOOGL": 175.00,
    "MSFT":  420.00,
    "AMZN":  185.00,
    "TSLA":  250.00,
    "NVDA":  800.00,
    "META":  500.00,
    "JPM":   195.00,
    "V":     280.00,
    "NFLX":  600.00,
}

TICKER_PARAMS = {
    "AAPL":  {"sigma": 0.22, "mu": 0.05},  # Moderate volatility
    "TSLA":  {"sigma": 0.50, "mu": 0.03},  # High volatility, low drift
    "NVDA":  {"sigma": 0.40, "mu": 0.08},  # High volatility, strong drift
    "JPM":   {"sigma": 0.18, "mu": 0.04},  # Low volatility (bank)
    "V":     {"sigma": 0.17, "mu": 0.04},  # Lowest volatility (payments)
    # ... etc
}

DEFAULT_PARAMS = {"sigma": 0.25, "mu": 0.05}  # For unknown tickers
```

Unknown tickers (dynamically added by the user) start at a random price between $50–$300 and use `DEFAULT_PARAMS`.

---

## Code Structure

### `GBMSimulator` — Pure Math Layer

`backend/app/market/simulator.py` — `GBMSimulator` class

Owns the price state and simulation math. Has no knowledge of asyncio, caching, or FastAPI.

```python
class GBMSimulator:

    def __init__(self, tickers: list[str], dt: float, event_probability: float):
        # Initializes _tickers, _prices, _params, and _cholesky

    def step(self) -> dict[str, float]:
        # Core hot path — called every 500ms
        # 1. Generate correlated normal draws via Cholesky
        # 2. Apply GBM formula per ticker
        # 3. Optionally apply random shock
        # 4. Return {ticker: new_price}

    def add_ticker(self, ticker: str) -> None:
        # Adds ticker to simulation, rebuilds Cholesky

    def remove_ticker(self, ticker: str) -> None:
        # Removes ticker from simulation, rebuilds Cholesky

    def get_price(self, ticker: str) -> float | None:
        # Current price for a ticker

    def get_tickers(self) -> list[str]:
        # Currently tracked tickers
```

### `SimulatorDataSource` — Async Adapter

`backend/app/market/simulator.py` — `SimulatorDataSource` class

Wraps `GBMSimulator` and implements the `MarketDataSource` interface. Bridges the synchronous math layer to the asyncio event loop.

```python
class SimulatorDataSource(MarketDataSource):

    async def start(self, tickers: list[str]) -> None:
        # 1. Creates GBMSimulator with initial tickers
        # 2. Seeds PriceCache with starting prices (instant first render)
        # 3. Launches _run_loop() as an asyncio background task

    async def stop(self) -> None:
        # Cancels the background task cleanly

    async def add_ticker(self, ticker: str) -> None:
        # Delegates to GBMSimulator.add_ticker()
        # Also seeds cache immediately (ticker has a price right away)

    async def remove_ticker(self, ticker: str) -> None:
        # Delegates to GBMSimulator.remove_ticker()
        # Also removes from cache

    async def _run_loop(self) -> None:
        # Core loop:
        while True:
            prices = self._sim.step()              # Compute new prices
            for ticker, price in prices.items():
                self._cache.update(ticker, price)  # Write to cache
            await asyncio.sleep(0.5)               # Wait 500ms
```

### Separation of Concerns

```
GBMSimulator          — math only (numpy, no asyncio)
    ↓ called by
SimulatorDataSource   — asyncio task management + cache writes
    ↓ writes to
PriceCache            — thread-safe price store
    ↓ read by
SSE endpoint          — pushes to browser clients
```

This separation makes the math independently testable without any async infrastructure.

---

## Update Cycle Timing

```
t=0ms    GBMSimulator.step() called
           → correlated GBM move for all n tickers
           → optional random shocks
           → returns {ticker: price} dict
         Cache updated for each ticker
         (SSE version counter bumps n times)

t=500ms  asyncio.sleep() completes
         Next step() called
```

With 10 tickers, each 500ms cycle generates 10 cache updates, triggering 10 SSE version increments. The SSE endpoint detects version changes and pushes all updated prices to connected clients.

---

## Adding a New Ticker at Runtime

When a user adds a ticker to the watchlist while the simulator is running:

```python
await simulator_source.add_ticker("PYPL")
```

Internally:
1. `GBMSimulator.add_ticker("PYPL")` is called
2. Starting price is looked up in `SEED_PRICES` (or random $50–300 if unknown)
3. GBM params are looked up in `TICKER_PARAMS` (or `DEFAULT_PARAMS` if unknown)
4. Cholesky matrix is rebuilt to include the new ticker's correlations
5. The new price is immediately written to the cache (so the UI can show a price right away, without waiting for the next tick)

---

## Testing the Simulator

The simulator has a dedicated test suite in `backend/tests/market/`:

| File | What it tests |
|------|--------------|
| `test_simulator.py` | GBM math correctness, Cholesky rebuild, random shocks, add/remove tickers |
| `test_simulator_source.py` | SimulatorDataSource lifecycle, cache writes, async behavior |

Key test patterns:

```python
# Verify prices stay positive (GBM invariant)
sim = GBMSimulator(["AAPL", "TSLA"], dt=0.001, event_probability=0.0)
for _ in range(1000):
    prices = sim.step()
    assert all(p > 0 for p in prices.values())

# Verify cache is seeded immediately on start
source = SimulatorDataSource(cache)
await source.start(["AAPL"])
assert cache.get_price("AAPL") is not None  # Available before first tick
```

---

## Live Demo

A Rich terminal demo visualizes the simulator output without needing the full app:

```bash
cd backend
uv run market_data_demo.py
```

Displays a live-updating table with all 10 tickers, color-coded price direction arrows, sparkline mini-charts, and a log of random shock events. Runs for 60 seconds or until Ctrl+C. Useful for tuning GBM parameters visually.
