"""Tests for the SSE streaming endpoint."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.market.cache import PriceCache
from app.market.stream import _generate_events, create_stream_router


class TestCreateStreamRouter:
    """Tests for the create_stream_router factory."""

    def test_returns_router_with_prices_route(self):
        """Test that the factory returns a router with the /prices route."""
        cache = PriceCache()
        router = create_stream_router(cache)

        routes = [r.path for r in router.routes]
        assert "/api/stream/prices" in routes

    def test_each_call_returns_independent_router(self):
        """Test that calling the factory twice returns separate routers."""
        cache = PriceCache()
        router1 = create_stream_router(cache)
        router2 = create_stream_router(cache)
        assert router1 is not router2

    def test_router_mounted_in_app(self):
        """Test that the router integrates with a FastAPI app without errors."""
        cache = PriceCache()
        app = FastAPI()
        router = create_stream_router(cache)
        # include_router should not raise
        app.include_router(router)
        # Route should appear in the app's route list
        paths = [r.path for r in app.routes]
        assert "/api/stream/prices" in paths


@pytest.mark.asyncio
class TestGenerateEvents:
    """Tests for the _generate_events async generator."""

    async def test_first_yield_is_retry_directive(self):
        """Test that the first event is the SSE retry directive."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.is_disconnected = AsyncMock(return_value=True)

        events = []
        async for event in _generate_events(cache, request, interval=0.01):
            events.append(event)

        assert events[0] == "retry: 1000\n\n"

    async def test_yields_price_data_when_cache_has_entries(self):
        """Test that price data is yielded when cache is populated."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.update("GOOGL", 175.0)

        request = MagicMock()
        request.client.host = "127.0.0.1"
        # First call returns not-disconnected so we get one data event,
        # second call disconnects to stop the loop.
        request.is_disconnected = AsyncMock(side_effect=[False, True])

        events = []
        async for event in _generate_events(cache, request, interval=0.01):
            events.append(event)

        # retry directive + data event
        assert len(events) == 2
        assert events[0] == "retry: 1000\n\n"
        assert events[1].startswith("data: ")

        payload = json.loads(events[1][len("data: "):].strip())
        assert "AAPL" in payload
        assert "GOOGL" in payload
        assert payload["AAPL"]["price"] == 190.0

    async def test_stops_on_client_disconnect(self):
        """Test that the generator stops when the client disconnects."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.is_disconnected = AsyncMock(return_value=True)

        events = []
        async for event in _generate_events(cache, request, interval=0.01):
            events.append(event)

        # Only the retry directive — disconnected before any data event
        assert len(events) == 1

    async def test_skips_send_when_version_unchanged(self):
        """Test that no data event is sent when cache version hasn't changed."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)

        request = MagicMock()
        request.client.host = "127.0.0.1"
        # Allow two loop iterations without changing cache, then disconnect
        request.is_disconnected = AsyncMock(side_effect=[False, False, True])

        events = []
        async for event in _generate_events(cache, request, interval=0.01):
            events.append(event)

        # retry + first data event only — second loop sees no version change
        assert len(events) == 2

    async def test_sends_new_event_when_version_changes(self):
        """Test that a new event is sent when the cache is updated between loops."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)

        call_count = 0

        async def is_disconnected_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Update cache between the first and second loop iteration
                cache.update("AAPL", 191.0)
            return call_count > 3

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.is_disconnected = AsyncMock(side_effect=is_disconnected_side_effect)

        events = []
        async for event in _generate_events(cache, request, interval=0.01):
            events.append(event)

        # retry + two data events (one for each version change)
        data_events = [e for e in events if e.startswith("data: ")]
        assert len(data_events) == 2

    async def test_empty_cache_produces_no_data_events(self):
        """Test that an empty cache produces no data events."""
        cache = PriceCache()  # Empty

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.is_disconnected = AsyncMock(side_effect=[False, True])

        events = []
        async for event in _generate_events(cache, request, interval=0.01):
            events.append(event)

        # retry directive only — no prices in cache
        assert len(events) == 1
        assert events[0] == "retry: 1000\n\n"

    async def test_data_event_contains_all_price_fields(self):
        """Test that data events contain all expected fields."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.update("AAPL", 191.0)  # Gives a non-flat direction

        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.is_disconnected = AsyncMock(side_effect=[False, True])

        events = []
        async for event in _generate_events(cache, request, interval=0.01):
            events.append(event)

        data_events = [e for e in events if e.startswith("data: ")]
        assert len(data_events) == 1

        payload = json.loads(data_events[0][len("data: "):].strip())
        aapl = payload["AAPL"]
        assert "ticker" in aapl
        assert "price" in aapl
        assert "previous_price" in aapl
        assert "timestamp" in aapl
        assert "change" in aapl
        assert "change_percent" in aapl
        assert "direction" in aapl
        assert aapl["direction"] == "up"
