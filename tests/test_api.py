"""
tests/test_api.py — Tests for FastAPI endpoints
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from httpx import AsyncClient, ASGITransport

from app import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.anyio
async def test_settings_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "llm_url" in data
    assert "llm_model" in data


@pytest.mark.anyio
async def test_generate_empty_topic_returns_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/generate",
            json={"topic": "   ", "minutes": 3, "dry_run": True},
        )
    assert resp.status_code == 400


@pytest.mark.anyio
@patch("agents.search_agent.DDGS")
async def test_generate_dry_run_streams_sse(mock_ddgs_cls, tmp_path):
    fake_results = [
        {"title": "A", "href": "https://example.com/a", "body": "Text."},
        {"title": "B", "href": "https://example.com/b", "body": "More."},
        {"title": "C", "href": "https://example.com/c", "body": "Even more."},
    ]
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = fake_results
    mock_ddgs_cls.return_value = mock_ddgs

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/generate",
            json={
                "topic": "API Test Topic",
                "minutes": 2,
                "dry_run": True,
                "output_dir": str(tmp_path),
            },
            timeout=60.0,
        )

    assert resp.status_code == 200
    # SSE response should contain JSON events
    body = resp.text
    assert len(body) > 0

    # Try to parse at least one SSE event
    events = []
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            if data_str:
                try:
                    events.append(json.loads(data_str))
                except json.JSONDecodeError:
                    pass

    # Should have at least some progress events and a final done event
    assert len(events) > 0
    # Last event should be done
    done_events = [e for e in events if e.get("done")]
    assert len(done_events) >= 1


@pytest.mark.anyio
async def test_episodes_list_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/episodes")
    assert resp.status_code == 200
    data = resp.json()
    assert "episodes" in data
    assert isinstance(data["episodes"], list)


@pytest.mark.anyio
async def test_rss_feed_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/feed.xml")
    assert resp.status_code == 200
    assert "xml" in resp.headers.get("content-type", "")
    assert "<rss" in resp.text
    assert "<channel>" in resp.text


@pytest.mark.anyio
async def test_episode_detail_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/episodes/nonexistent_episode_12345")
    assert resp.status_code == 404
