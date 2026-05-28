# Massive (formerly Polygon.io) REST API — Stock Price Reference

Polygon.io rebranded as **Massive** on October 30, 2025. Existing API keys, accounts, and code continue to work. The SDK now defaults to `api.massive.com`; `api.polygon.io` remains supported for an extended period.

---

## Authentication

All requests require an API key. Pass it either:

- As a query parameter: `?apiKey=YOUR_KEY`
- As a Bearer token header: `Authorization: Bearer YOUR_KEY`

```python
from massive import RESTClient

client = RESTClient(api_key="YOUR_MASSIVE_API_KEY")
```

---

## Python SDK

Install the official client:

```bash
pip install -U massive
```

The `RESTClient` is **synchronous**. In async contexts (e.g., FastAPI), wrap calls with `asyncio.to_thread()`:

```python
import asyncio
from massive import RESTClient

client = RESTClient(api_key="YOUR_KEY")

# In an async function:
result = await asyncio.to_thread(client.get_last_trade, ticker="AAPL")
```

---

## Key Endpoints

### 1. Full Market Snapshot (Batch — Recommended for Multi-Ticker)

Retrieve current prices for multiple tickers in a single API call. This is the most efficient endpoint for a watchlist.

**REST:**
```
GET /v2/snapshot/locale/us/markets/stocks/tickers
    ?tickers=AAPL,MSFT,GOOGL
    &apiKey=YOUR_KEY
```

**SDK:**
```python
from massive.rest.models import SnapshotMarketType

snapshots = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,
    tickers=["AAPL", "MSFT", "GOOGL", "TSLA"],
)

for snap in snapshots:
    price = snap.last_trade.price
    timestamp_ms = snap.last_trade.timestamp  # Unix milliseconds
    print(f"{snap.ticker}: ${price:.2f}")
```

**Response fields per snapshot object:**
| Field | Type | Description |
|-------|------|-------------|
| `ticker` | str | Ticker symbol |
| `last_trade.price` | float | Most recent trade price |
| `last_trade.timestamp` | int | Unix milliseconds |
| `last_trade.size` | int | Shares traded |
| `day.o` / `.h` / `.l` / `.c` | float | Today's OHLC |
| `day.v` | float | Today's volume |
| `prevDay.c` | float | Previous day's close |
| `todaysChange` | float | Absolute price change today |
| `todaysChangePerc` | float | % change today |
| `updated` | int | Last update timestamp (Unix nanoseconds) |

**Plan notes:**
- Requires **Stocks Starter** plan or higher (not available on Basic)
- Data is **15-minute delayed** on Starter/Developer; **real-time** on Advanced/Business

---

### 2. Unified Snapshot (Up to 250 Tickers)

A newer v3 endpoint supporting up to 250 tickers with richer filtering.

**REST:**
```
GET /v3/snapshot
    ?ticker.any_of=AAPL,MSFT,TSLA
    &limit=250
    &apiKey=YOUR_KEY
```

**SDK (raw requests):**
```python
import requests

response = requests.get(
    "https://api.massive.com/v3/snapshot",
    params={
        "ticker.any_of": "AAPL,MSFT,TSLA,NVDA",
        "limit": 250,
        "apiKey": "YOUR_KEY",
    }
)
data = response.json()

for result in data.get("results", []):
    ticker = result["ticker"]
    last_trade = result.get("last_trade", {})
    price = last_trade.get("price")
    print(f"{ticker}: ${price}")
```

**Response fields:**
| Field | Description |
|-------|-------------|
| `ticker` | Symbol |
| `last_trade.price` | Latest trade price |
| `last_quote.bid` / `.ask` | Best bid/ask |
| `session.open` | Today's open |
| `session.close` | Today's close (if market closed) |
| `session.change` | Absolute change |
| `session.change_percent` | % change |
| `market_status` | `open`, `closed`, `early_trading`, `late_trading` |

---

### 3. Last Trade (Single Ticker)

Get the most recent trade for one ticker.

**REST:**
```
GET /v2/last/trade/{ticker}?apiKey=YOUR_KEY
```

**SDK:**
```python
trade = client.get_last_trade(ticker="AAPL")
print(f"Price: {trade.price}, Size: {trade.size}")
print(f"Timestamp: {trade.timestamp}")  # Unix nanoseconds
```

**Response fields:**
| Field | Description |
|-------|-------------|
| `price` | Trade price |
| `size` | Number of shares |
| `exchange` | Exchange ID |
| `timestamp` | Unix nanoseconds |
| `conditions` | Trade condition codes |

---

### 4. Previous Day Bar (Single Ticker)

Get the previous trading day's OHLCV for a ticker — useful for computing daily change %.

**REST:**
```
GET /v2/aggs/ticker/{ticker}/prev?apiKey=YOUR_KEY
```

**SDK:**
```python
prev = client.get_previous_close_agg(ticker="AAPL")
# prev is a list; take first result
bar = prev[0] if prev else None
if bar:
    print(f"Prev close: {bar.c}, Open: {bar.o}, Volume: {bar.v}")
```

**Response fields:**
| Field | Description |
|-------|-------------|
| `T` | Ticker symbol |
| `o` | Open |
| `h` | High |
| `l` | Low |
| `c` | Close |
| `v` | Volume |
| `vw` | Volume-weighted average price |
| `t` | Unix milliseconds (bar start) |

---

### 5. Daily Market Summary (All Tickers, One Date)

Get OHLCV for all U.S. stocks on a specific trading date. Useful for batch daily-open seeding.

**REST:**
```
GET /v2/aggs/grouped/locale/us/market/stocks/{date}
    ?adjusted=true
    &apiKey=YOUR_KEY
```

**SDK (raw requests):**
```python
import requests

response = requests.get(
    "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/2025-05-27",
    params={"adjusted": True, "apiKey": "YOUR_KEY"}
)
data = response.json()

prices = {item["T"]: item["c"] for item in data.get("results", [])}
print(f"AAPL close: {prices.get('AAPL')}")
```

---

## Rate Limits by Plan

| Plan | Rate Limit | Poll Interval (10 tickers) |
|------|-----------|---------------------------|
| Basic | 5 req/min | Not available (no snapshot) |
| Starter | 5 req/min | ~15 seconds |
| Developer | Higher | ~5–10 seconds |
| Advanced | Higher | ~2–5 seconds |
| Business | Unlimited | ~1–2 seconds |

For a 10-ticker watchlist using the batch snapshot endpoint:
- **Free/Starter**: one API call per poll → 15-second interval stays safely within 5 req/min
- **Paid tiers**: reduce interval to 2–5 seconds for near-real-time updates

---

## Timestamp Conventions

The Massive API uses several timestamp formats — be careful when converting:

| Endpoint | Unit | Convert to seconds |
|----------|------|--------------------|
| Last Trade `.timestamp` | Nanoseconds | `/ 1_000_000_000` |
| Snapshot `.last_trade.timestamp` | Milliseconds | `/ 1000` |
| Aggregates `.t` | Milliseconds | `/ 1000` |

---

## Complete Working Example

```python
"""Fetch current prices for a watchlist using the batch snapshot endpoint."""
import asyncio
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def fetch_prices(api_key: str) -> dict[str, float]:
    """Return {ticker: current_price} for all tickers in one API call."""
    client = RESTClient(api_key=api_key)
    snapshots = client.get_snapshot_all(
        market_type=SnapshotMarketType.STOCKS,
        tickers=WATCHLIST,
    )

    prices = {}
    for snap in snapshots:
        try:
            prices[snap.ticker] = snap.last_trade.price
        except (AttributeError, TypeError):
            pass  # Ticker had no last trade data
    return prices


async def fetch_prices_async(api_key: str) -> dict[str, float]:
    """Async wrapper — runs the synchronous SDK call in a thread pool."""
    return await asyncio.to_thread(fetch_prices, api_key)


if __name__ == "__main__":
    import os
    api_key = os.environ["MASSIVE_API_KEY"]
    prices = fetch_prices(api_key)
    for ticker, price in sorted(prices.items()):
        print(f"{ticker:6s}  ${price:>10.2f}")
```

---

## Error Handling

Common HTTP status codes from the Massive API:

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process results |
| 401 | Invalid or missing API key | Check `MASSIVE_API_KEY` |
| 403 | Endpoint not available on your plan | Upgrade plan |
| 404 | Ticker not found | Remove from watchlist |
| 429 | Rate limit exceeded | Back off, increase poll interval |
| 500 | Server error | Log and retry on next interval |

The SDK raises exceptions for non-200 responses. Wrap calls in try/except and log errors rather than crashing — the poll loop will retry on the next interval.

---

## Links

- [Massive API Docs](https://massive.com/docs)
- [Python Client (GitHub)](https://github.com/massive-com/client-python)
- [REST Quickstart](https://massive.com/docs/rest/quickstart)
- [Stocks Overview](https://massive.com/docs/rest/stocks/overview)
- [Full Market Snapshot](https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot)
- [Unified Snapshot](https://massive.com/docs/rest/stocks/snapshots/unified-snapshot)
- [Pricing](https://massive.com/pricing)
