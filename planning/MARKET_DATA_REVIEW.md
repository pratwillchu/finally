# Market Data Backend — Code Review

**Date:** 2026-05-28
**Reviewer:** Claude Code (claude-sonnet-4-6)
**Scope:** `backend/app/market/` (8 source files) and `backend/tests/market/` (6 test files)
**Previous review:** `planning/archive/MARKET_DATA_REVIEW.md` (2026-02-10)

---

## 1. Test Results

**73 tests collected, 73 passed, 0 failed.** All tests pass cleanly.

```
tests/market/test_cache.py              13 passed
tests/market/test_factory.py             7 passed
tests/market/test_massive.py            13 passed
tests/market/test_models.py             11 passed
tests/market/test_simulator.py          19 passed
tests/market/test_simulator_source.py   10 passed
```

Run command: `python3 -m pytest tests/market/ -v` (1.88s)

**Lint (ruff):** `All checks passed.` Zero warnings in source or test files.

---

## 2. Coverage

```
Name                           Stmts   Miss  Cover   Missing
------------------------------------------------------------
app/market/__init__.py             6      0   100%
app/market/cache.py               39      0   100%
app/market/factory.py             15      0   100%
app/market/interface.py           13      0   100%
app/market/massive_client.py      67      4    94%   85-87, 125
app/market/models.py              26      0   100%
app/market/seed_prices.py          8      0   100%
app/market/simulator.py          139      3    98%   149, 268-269
app/market/stream.py              36     24    33%   26-48, 62-87
------------------------------------------------------------
TOTAL                            349     31    91%
```

**91% overall.** Five modules at 100%. Three with expected gaps:

- **`massive_client.py` (94%):** Lines 85–87 are the `_poll_loop` while-body (tested indirectly via `test_stop_cancels_task`); line 125 is the literal `get_snapshot_all` SDK call (requires a live API key, correctly not tested directly).
- **`simulator.py` (98%):** Line 149 is the duplicate-guard `return` in `_add_ticker_internal` — unreachable because `add_ticker` checks `if ticker in self._prices` before calling it. Lines 268–269 are the `logger.exception` path inside `_run_loop` exception handling — never triggered by any test.
- **`stream.py` (33%):** The SSE route handler and `_generate_events` generator require a running ASGI server to exercise. No integration tests exist for the streaming layer.

---

## 3. Issues Found

### 3.1 Deprecated `conftest.py` Fixture — 73 Warnings (Severity: Low)

`tests/conftest.py` defines an `event_loop_policy` fixture:

```python
@pytest.fixture
def event_loop_policy():
    import asyncio
    return asyncio.DefaultEventLoopPolicy()
```

This fixture is deprecated in pytest-asyncio and generates one `PytestDeprecationWarning` per test (73 total). With `asyncio_mode = "auto"` already set in `pyproject.toml`, this fixture is also unnecessary — the default event loop policy is used automatically.

**Fix:** Delete the fixture (or the entire conftest body if nothing else is needed):
```python
# tests/conftest.py  — can be removed entirely or left empty
```

### 3.2 `timestamp=0` Falsy Bug in `cache.py` (Severity: Low)

`cache.py:29`:
```python
ts = timestamp or time.time()
```

If `timestamp=0.0` is passed, Python treats `0.0` as falsy and falls back to `time.time()`, silently ignoring the provided value. The correct idiom is:

```python
ts = timestamp if timestamp is not None else time.time()
```

In practice this will never fire because Massive timestamps are Unix milliseconds divided by 1000 (always a large positive float), and the simulator passes `None`. But it is a latent correctness bug and the `None`-check pattern is the correct one here.

### 3.3 `version` Property Read Without Lock (Severity: Low)

`cache.py` (the `version` property):
```python
@property
def version(self) -> int:
    return self._version  # No lock acquired
```

All other reads in `PriceCache` acquire `self._lock`. The `_version` write *is* under the lock (inside `update()`). On CPython, reading an `int` is atomic due to the GIL, so this is not a correctness problem today. However, it is inconsistent and would become unsafe on a no-GIL Python build (CPython 3.13+ free-threaded mode). Adding `with self._lock: return self._version` is a one-liner fix.

### 3.4 Module-Level Router Singleton in `stream.py` (Severity: Low)

`stream.py:17`:
```python
router = APIRouter(prefix="/api/stream", tags=["streaming"])

def create_stream_router(price_cache: PriceCache) -> APIRouter:
    @router.get("/prices")  # registers on the module-level router
    async def stream_prices(request: Request) -> StreamingResponse:
        ...
    return router
```

`create_stream_router` is named like a factory but actually registers a new route on the same module-level `router` every time it is called. Calling it twice would register `/prices` twice. In production this is fine (called exactly once), but it makes the function impossible to use safely in tests without resetting module state. A true factory would create a new `APIRouter` inside the function body.

**Fix:**
```python
def create_stream_router(price_cache: PriceCache) -> APIRouter:
    router = APIRouter(prefix="/api/stream", tags=["streaming"])
    
    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        ...
    return router
```

### 3.5 `add_ticker` Normalisation Inconsistency (Severity: Low)

`MassiveDataSource.add_ticker` normalises its input:
```python
ticker = ticker.upper().strip()
```

`SimulatorDataSource.add_ticker` does not:
```python
async def add_ticker(self, ticker: str) -> None:
    if self._sim:
        self._sim.add_ticker(ticker)  # raw input passed through
```

If the API route that calls `add_ticker` validates the format, this is harmless. But the `MarketDataSource` interface contract doesn't specify normalisation as the caller's responsibility — both implementations should behave the same. Move the normalisation to either both implementations or to the interface level (a concrete helper method).

### 3.6 SSE Tests Absent (Severity: Low)

`stream.py` has 33% coverage and no dedicated tests. The SSE layer is the primary delivery path for prices to the frontend — it deserves at least minimal test coverage. An httpx `AsyncClient` against a minimal FastAPI test app would cover the generator, version-change detection, and disconnect handling without requiring a real browser.

---

## 4. Issues Resolved Since Previous Review

The February 2026 review identified 7 issues. All are confirmed resolved:

| # | Issue | Status |
|---|-------|--------|
| 1 | `pyproject.toml` missing `[tool.hatch.build.targets.wheel]` | ✅ Fixed |
| 2 | Massive tests failing (lazy import + missing package) | ✅ Fixed — `massive` installed, tests pass |
| 3 | `_generate_events` return type annotated as `-> None` | ✅ Fixed — now `-> AsyncGenerator[str, None]` |
| 4 | `GBMSimulator` had no public `get_tickers()` method | ✅ Fixed — method added |
| 5 | `DEFAULT_CORR` constant defined but unused | ✅ Fixed — removed |
| 6 | Unused imports in 4 test files | ✅ Fixed — ruff passes clean |
| 7 | Massive mocks targeting non-existent module-level names | ✅ Fixed |

---

## 5. Architecture Assessment

The subsystem is well-designed and the implementation matches the design documents closely.

### Strengths

**Strategy pattern is cleanly executed.** `SimulatorDataSource` and `MassiveDataSource` are interchangeable behind `MarketDataSource`. The factory reads a single env var. Downstream code (SSE, portfolio) is completely agnostic to which source is active.

**GBM math is correct.** The log-normal formula `S(t+dt) = S(t) * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z)` guarantees positive prices, uses the Itô-corrected drift, and scales `dt` correctly against a trading-year denominator. Prices cannot go negative or diverge to infinity for any reasonable sigma and dt.

**Cholesky decomposition for correlated moves.** Generating independent normals and projecting through the lower-triangular Cholesky factor is the standard and mathematically correct approach. The sector-based correlation structure (tech 0.6, finance 0.5, cross 0.3, TSLA special-cased to 0.3 with everything) is realistic and the implementation correctly rebuilds the matrix only on add/remove, not every tick.

**`PriceCache` as single point of truth.** Producers write, consumers read. The version counter lets SSE skip sends when nothing changed (important with Massive's 15s poll interval vs SSE's 0.5s push interval). Thread-safety via `threading.Lock` is the right choice since Massive runs its synchronous SDK in `asyncio.to_thread()`.

**Immediate cache seeding.** Both `SimulatorDataSource.start()` and `SimulatorDataSource.add_ticker()` write seed prices to the cache before returning. The SSE client always has data on first connect — no blank-screen flash.

**Resilient error handling.** Both `_run_loop` (simulator) and `_poll_once` (Massive) catch-and-continue on errors. A bad Massive API key logs an error and retries on the next interval rather than crashing the app. Individual malformed snapshots are skipped without aborting the batch.

**`PriceUpdate` model is clean.** `frozen=True, slots=True` is correct for a high-volume value type. Computed properties (`change`, `change_percent`, `direction`) are derived from stored fields and can never be inconsistent. `to_dict()` is the single serialisation point.

### Observations

**TSLA correlation logic is slightly paradoxical.** TSLA is a member of `CORRELATION_GROUPS["tech"]` but `_pairwise_correlation` special-cases it to 0.3 (same as cross-sector) with everything, including other tech stocks. The special case runs before the tech-group check so behavior is correct, but TSLA's membership in the tech set is misleading. Consider removing TSLA from the tech set and relying on the TSLA special case alone.

**Shock events use `random.random()` not `np.random`.** This is fine, but there is a subtle mixing of two random number generators (`numpy.random` for GBM, `random` for shocks). These are independent streams, which is not an issue for the simulation, but worth noting for reproducibility if a fixed seed is ever needed for testing.

**`test_prices_change_over_time` is probabilistically sound.** The test steps the simulator 1000 times and asserts the price moved. With `DEFAULT_DT = 8.48e-8` and `sigma=0.22`, the expected total variance over 1000 steps is `sigma^2 * 1000 * dt ≈ 1.9e-3`. It is theoretically possible (but astronomically unlikely) for the price to return exactly to the seed. The test is reliable in practice.

---

## 6. Test Quality Assessment

The test suite is comprehensive for the units it covers. Key positive patterns:

- **Edge cases are covered.** Empty ticker list, duplicate add, remove-nonexistent, malformed Massive snapshot, zero previous price in change_percent, whitespace/case normalisation.
- **Async tests use real timing sparingly.** `test_prices_update_over_time` and similar use `asyncio.sleep` with generous margins rather than tight timing assertions. This makes the tests resilient to CI scheduling jitter.
- **Massive tests use `patch.object` on `_fetch_snapshots`**, which is the correct mock target (the internal synchronous method), rather than patching the network layer.
- **Factory tests properly isolate env vars** using `patch.dict(os.environ, ..., clear=True)`.

Gaps:

- No SSE integration test (noted in §3.6).
- No concurrent write test for `PriceCache` (lock correctness verified by inspection only).
- No test for the full 10-ticker default set through `GBMSimulator` — in particular, that `np.linalg.cholesky` succeeds for the default correlation matrix (it will, but an explicit regression test would catch future parameter changes that make the matrix non-positive-definite).

---

## 7. Verdict

**The market data backend is production-ready for its scope.** All 73 tests pass, linting is clean, and the architecture matches the design documents. The issues found are all low-severity.

### Recommended fixes before downstream integration

| Priority | Issue | Effort |
|----------|-------|--------|
| Low | Remove deprecated `conftest.py` fixture (eliminates 73 warnings) | 1 line |
| Low | Fix `timestamp or time.time()` → `timestamp if timestamp is not None else time.time()` in `cache.py:29` | 1 line |
| Low | Fix `create_stream_router` to create a new `APIRouter` locally (eliminates singleton footgun) | 2 lines |
| Low | Add `version` property lock for future-proofing | 1 line |

### Nice to have

| Issue | Effort |
|-------|--------|
| SSE integration test (httpx AsyncClient) | ~30 lines |
| Normalise `add_ticker` input in `SimulatorDataSource` to match `MassiveDataSource` | 1 line |
| Move TSLA out of the tech correlation group (or add a comment explaining the duplication) | 1 line |
