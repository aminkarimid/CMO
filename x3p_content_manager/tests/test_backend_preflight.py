import os

import x3p_content_manager.app.backend_health as bh


def test_preflight_fails_fast_when_openai_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(bh, "_detect_configured_providers", lambda: {"openai"})
    monkeypatch.setattr(bh, "_ping_openai_model", lambda model, timeout_sec=6: (False, None, "missing_api_key"))
    monkeypatch.setattr(bh, "_preflight_generation_check_enabled", lambda: False)

    status = bh.preflight_backend()
    assert status.ok is False
    assert status.provider == "openai"
    assert status.details.get("failure_reason") == "missing_api_key"


def test_preflight_fails_fast_when_model_ping_fails(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(bh, "_detect_configured_providers", lambda: {"openai"})
    monkeypatch.setattr(bh, "_ping_openai_model", lambda model, timeout_sec=6: (False, 123.0, "openai_timeout"))
    monkeypatch.setattr(bh, "_preflight_generation_check_enabled", lambda: False)

    status = bh.preflight_backend()
    assert status.ok is False
    assert status.provider == "openai"
    assert status.details.get("failure_reason") == "openai_timeout"


def test_preflight_passes_when_openai_ping_succeeds(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(bh, "_detect_configured_providers", lambda: {"openai"})
    monkeypatch.setattr(bh, "_ping_openai_model", lambda model, timeout_sec=6: (True, 88.1, None))
    monkeypatch.setattr(bh, "_preflight_generation_check_enabled", lambda: True)
    monkeypatch.setattr(bh, "_ping_openai_generation", lambda model, timeout_sec=8: (True, 44.0, None))

    status = bh.preflight_backend()
    assert status.ok is True
    assert status.provider == "openai"
    assert status.details.get("llm_ping_ms") == 88.1
    assert status.details.get("generation_ping_ms") == 44.0


def test_preflight_fails_fast_when_generation_check_reports_quota(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(bh, "_detect_configured_providers", lambda: {"openai"})
    monkeypatch.setattr(bh, "_ping_openai_model", lambda model, timeout_sec=6: (True, 50.0, None))
    monkeypatch.setattr(bh, "_preflight_generation_check_enabled", lambda: True)
    monkeypatch.setattr(bh, "_ping_openai_generation", lambda model, timeout_sec=8: (False, 60.0, "insufficient_quota"))

    status = bh.preflight_backend()
    assert status.ok is False
    assert status.provider == "openai"
    assert status.details.get("failure_reason") == "insufficient_quota"


def test_apply_runtime_backend_sets_openai_env(monkeypatch):
    monkeypatch.delenv("X3P_ACTIVE_BACKEND", raising=False)
    monkeypatch.delenv("X3P_OPENAI_MODEL", raising=False)
    status = bh.BackendStatus(
        ok=True,
        provider="openai",
        message="ok",
        details={"llm_model": "gpt-4o-mini", "configured_providers": ["openai", "ollama"]},
    )

    warning = bh.apply_runtime_backend(status)
    assert os.getenv("X3P_ACTIVE_BACKEND") == "openai"
    assert os.getenv("X3P_OPENAI_MODEL") == "gpt-4o-mini"
    assert "OpenAI primary policy" in (warning or "")
