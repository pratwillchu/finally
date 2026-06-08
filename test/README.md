# FinAlly E2E Tests

End-to-end tests using Playwright against a running FinAlly container.

## Quick Start

```bash
# From project root:

# 1. Build and start the test container
docker compose -f test/docker-compose.test.yml up -d --build

# 2. Wait for health check to pass
docker compose -f test/docker-compose.test.yml ps

# 3. Install Playwright
cd test && npm install && npx playwright install chromium

# 4. Run tests
npm test

# 5. View report
npm run test:report

# 6. Cleanup
cd .. && docker compose -f test/docker-compose.test.yml down -v
```

## Environment

Tests run with `LLM_MOCK=true` — no OpenRouter API key needed.
Set `BASE_URL` env var to test against a different host (default: http://localhost:8000).
