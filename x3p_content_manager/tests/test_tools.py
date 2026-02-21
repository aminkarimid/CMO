import requests

from x3p_content_manager.tools import tavily_tool, semantic_scholar_tool, pubmed_tool


def test_tavily_tool_missing_key_returns_error(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    result = tavily_tool.run(query="care economy", max_results=1)
    assert result["status"] == "error"
    assert "TAVILY_API_KEY" in result["message"]


def test_semantic_scholar_tool_handles_request_errors(monkeypatch):
    def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", _raise)
    result = semantic_scholar_tool.run(query="x3p")
    assert result["status"] == "error"
    assert "Semantic Scholar" in result["message"]


def test_semantic_scholar_tool_uses_api_key(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_KEY", "sekret")

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    def _fake_get(url, params=None, headers=None, timeout=None):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["params"] = params or {}
        return _Resp()

    monkeypatch.setattr(requests, "get", _fake_get)

    semantic_scholar_tool.run(query="care economy", limit=1)

    assert captured["url"].endswith("/paper/search")
    assert captured["headers"].get("x-api-key") == "sekret"
    assert captured["params"]["limit"] == 1



def test_pubmed_tool_handles_request_errors(monkeypatch):
    def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise requests.RequestException("fail")

    monkeypatch.setattr(requests, "get", _raise)
    result = pubmed_tool.run(query="care")
    assert result["status"] == "error"
    assert "PubMed" in result["message"]
