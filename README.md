# FinAlly — AI Trading Workstation

An AI-powered trading workstation that streams live market data, lets you trade a simulated portfolio, and includes an LLM chat assistant that can analyze your positions and execute trades on your behalf. Built to look and feel like a modern Bloomberg terminal with an AI copilot.

## Features

- **Live price streaming** via SSE — prices flash green/red on every tick
- **Sparkline mini-charts** per ticker, accumulated from the live stream
- **Simulated portfolio** — $10,000 in virtual cash, instant market-order fills
- **Portfolio heatmap** — treemap sized by weight, colored by P&L
- **P&L chart** — total portfolio value over time
- **AI chat assistant** — ask questions, get analysis, and have the AI execute trades for you

## Quick Start

```bash
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env

./scripts/start_mac.sh      # macOS/Linux
# or
.\scripts\start_windows.ps1 # Windows PowerShell
```

Then open [http://localhost:8000](http://localhost:8000).

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for AI chat |
| `MASSIVE_API_KEY` | No | Polygon.io key for real market data (simulator used if absent) |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses (testing) |

## Architecture

Single Docker container on port 8000:

- **Frontend**: Next.js (TypeScript), statically exported and served by FastAPI
- **Backend**: FastAPI (Python/uv) — REST + SSE endpoints
- **Database**: SQLite, volume-mounted at `db/finally.db`
- **Market data**: Built-in GBM price simulator (default) or Massive REST API
- **AI**: LiteLLM → OpenRouter → Cerebras inference

## Development

```bash
# Backend
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Testing

```bash
# Backend unit tests
cd backend && uv run pytest

# E2E tests (requires Docker)
cd test && docker compose -f docker-compose.test.yml up --abort-on-container-exit
```
