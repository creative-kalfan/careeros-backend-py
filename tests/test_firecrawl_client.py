"""Tests for the Firecrawl API client (mocked HTTP; no real API usage)."""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.crawlers.firecrawl_client import (
    FirecrawlAuthError,
    FirecrawlClient,
    FirecrawlConfigurationError,
    FirecrawlError,
    FirecrawlServerError,
)


def _response(status: int = 200, payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    if payload is not None:
        response.json.return_value = payload
    else:
        response.json.side_effect = ValueError("no json")
    return response


def _client(mock_http: AsyncMock | None = None, api_key: str | None = "test-key") -> FirecrawlClient:
    return FirecrawlClient(
        api_key=api_key,
        client=mock_http or AsyncMock(),
        max_retries=0,
    )


def test_missing_api_key_raises_configuration_error():
    client = _client(api_key="")
    with pytest.raises(FirecrawlConfigurationError):
        client._require_key()


@pytest.mark.asyncio
async def test_missing_api_key_never_pretends_success():
    client = _client(api_key="")
    with pytest.raises(FirecrawlConfigurationError):
        await client.map("https://stripe.com/careers")


@pytest.mark.asyncio
async def test_successful_map_returns_links():
    mock_http = AsyncMock()
    mock_http.post.return_value = _response(200, {"links": ["https://stripe.com/jobs/1"]})
    client = _client(mock_http)
    links = await client.map("https://stripe.com/careers")
    assert links == ["https://stripe.com/jobs/1"]
    # Authorization header carries the key, key never appears in logs
    headers = mock_http.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_401_raises_auth_error():
    mock_http = AsyncMock()
    mock_http.post.return_value = _response(401)
    client = _client(mock_http)
    with pytest.raises(FirecrawlAuthError):
        await client.scrape("https://stripe.com/jobs/1")


@pytest.mark.asyncio
async def test_429_raises_rate_limit_after_retries(monkeypatch):
    mock_http = AsyncMock()
    mock_http.post.return_value = _response(429)
    monkeypatch.setattr("app.crawlers.firecrawl_client.asyncio.sleep", AsyncMock())
    client = FirecrawlClient(api_key="k", client=mock_http, max_retries=2)
    from app.crawlers.firecrawl_client import FirecrawlRateLimitError

    with pytest.raises(FirecrawlRateLimitError):
        await client.scrape("https://stripe.com/jobs/1")
    assert mock_http.post.await_count == 3  # 1 + 2 retries


@pytest.mark.asyncio
async def test_5xx_raises_server_error_after_retries(monkeypatch):
    mock_http = AsyncMock()
    mock_http.post.return_value = _response(500)
    monkeypatch.setattr("app.crawlers.firecrawl_client.asyncio.sleep", AsyncMock())
    client = FirecrawlClient(api_key="k", client=mock_http, max_retries=2)
    with pytest.raises(FirecrawlServerError):
        await client.scrape("https://stripe.com/jobs/1")


@pytest.mark.asyncio
async def test_timeout_raises_typed_error(monkeypatch):
    mock_http = AsyncMock()
    mock_http.post.side_effect = httpx.TimeoutException("timed out")
    monkeypatch.setattr("app.crawlers.firecrawl_client.asyncio.sleep", AsyncMock())
    client = FirecrawlClient(api_key="k", client=mock_http, max_retries=1)
    with pytest.raises(FirecrawlError):
        await client.scrape("https://stripe.com/jobs/1")


@pytest.mark.asyncio
async def test_other_4xx_does_not_retry():
    mock_http = AsyncMock()
    mock_http.post.return_value = _response(422)
    client = _client(mock_http)
    with pytest.raises(FirecrawlError):
        await client.scrape("https://stripe.com/jobs/1")
    assert mock_http.post.await_count == 1


@pytest.mark.asyncio
async def test_malformed_json_raises_typed_error():
    mock_http = AsyncMock()
    mock_http.post.return_value = _response(200, None)
    client = _client(mock_http)
    with pytest.raises(FirecrawlError):
        await client.scrape("https://stripe.com/jobs/1")


@pytest.mark.asyncio
async def test_error_messages_never_contain_api_key():
    secret = "sk-super-secret-key"
    mock_http = AsyncMock()
    mock_http.post.return_value = _response(401)
    client = FirecrawlClient(api_key=secret, client=mock_http)
    try:
        await client.scrape("https://stripe.com/jobs/1")
        raised = None
    except FirecrawlError as exc:
        raised = exc
    assert raised is not None
    assert secret not in str(raised)
