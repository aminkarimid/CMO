from x3p_content_manager.tools import (
    brand_retriever_tool,
    social_trends_tool,
    tavily_tool,
    trend_verifier_tool,
    x3p_site_snapshot_tool,
)


def test_tavily_tool_missing_key_returns_error(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    result = tavily_tool.run(query="care economy", max_results=1)
    assert result["status"] == "error"
    assert "TAVILY_API_KEY" in result["message"]


def test_social_trends_returns_error_when_sources_unavailable(monkeypatch):
    monkeypatch.setattr(
        tavily_tool,
        "run",
        lambda **_kwargs: {"status": "error", "message": "down", "data": []},
    )

    result = social_trends_tool.run(include_platforms="web", limit=2)
    assert result["status"] == "error"
    assert "No trend items were verified" in result["message"]


def test_trend_verifier_requires_multiple_sources(monkeypatch):
    monkeypatch.setattr(
        tavily_tool,
        "run",
        lambda **_kwargs: {"status": "ok", "data": [{"url": "https://example.com", "domain": "example.com"}]},
    )
    result = trend_verifier_tool.run(query="care workforce", min_sources=2, max_results=4)
    assert result["status"] == "error"
    assert "Insufficient verified sources" in result["message"]


def test_x3p_site_snapshot_handles_fetch_failure(monkeypatch):
    monkeypatch.setattr(
        x3p_site_snapshot_tool,
        "_run",
        lambda **_kwargs: {"status": "error", "message": "Unable to fetch x3p.ai pages for snapshot.", "data": []},
    )
    result = x3p_site_snapshot_tool.run()
    assert result["status"] == "error"


def test_brand_retriever_requires_query():
    result = brand_retriever_tool.run(query="")
    assert result["status"] == "error"
