from x3p_content_manager.app.backend_health import BackendStatus
from x3p_content_manager.app import runtime_health as rh


def test_run_preflight_checks_fails_when_backend_not_ready(monkeypatch):
    backend = BackendStatus(ok=False, provider="openai", message="missing key", details={})
    monkeypatch.setattr(rh, "preflight_backend", lambda: backend)

    report = rh.run_preflight_checks()
    assert report.ok is False
    assert report.message == "missing key"
    assert report.checks == []


def test_run_preflight_checks_fails_on_critical_tool_probe(monkeypatch):
    backend = BackendStatus(ok=True, provider="openai", message="ok", details={})
    monkeypatch.setattr(rh, "preflight_backend", lambda: backend)
    monkeypatch.setattr(
        rh,
        "_probe_tavily",
        lambda: rh.HealthCheck(name="tavily_tool", ok=False, message="down", critical=True),
    )
    monkeypatch.setattr(
        rh,
        "_probe_x3p_site",
        lambda: rh.HealthCheck(name="x3p_site", ok=True, message="ok", critical=True),
    )
    monkeypatch.setattr(
        rh,
        "_probe_brand_retriever",
        lambda: rh.HealthCheck(name="brand_retriever_tool", ok=True, message="ok", critical=False),
    )

    report = rh.run_preflight_checks()
    assert report.ok is False
    assert "tavily_tool" in report.message
    assert "tavily_tool" in report.details.get("critical_failures", [])


def test_run_preflight_checks_passes_when_all_critical_checks_pass(monkeypatch):
    backend = BackendStatus(ok=True, provider="openai", message="ok", details={})
    monkeypatch.setattr(rh, "preflight_backend", lambda: backend)
    monkeypatch.setattr(
        rh,
        "_probe_tavily",
        lambda: rh.HealthCheck(name="tavily_tool", ok=True, message="ok", critical=True),
    )
    monkeypatch.setattr(
        rh,
        "_probe_x3p_site",
        lambda: rh.HealthCheck(name="x3p_site", ok=True, message="ok", critical=True),
    )
    monkeypatch.setattr(
        rh,
        "_probe_brand_retriever",
        lambda: rh.HealthCheck(name="brand_retriever_tool", ok=True, message="ok", critical=False),
    )

    report = rh.run_preflight_checks()
    assert report.ok is True
    assert report.backend.details.get("tool_health", {}).get("tavily_tool", {}).get("ok") is True
