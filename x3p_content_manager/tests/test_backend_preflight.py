import os

import x3p_content_manager.app.backend_health as bh


def test_preflight_fails_fast_when_configured_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(bh, "_detect_configured_providers", lambda: {"ollama"})
    monkeypatch.setattr(bh, "_ollama_available", lambda: False)

    status = bh.preflight_backend()
    assert status.ok is False
    assert status.provider == "ollama"


def test_preflight_fails_fast_when_configured_openai_missing_key(monkeypatch):
    monkeypatch.setattr(bh, "_detect_configured_providers", lambda: {"openai"})
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    status = bh.preflight_backend()
    assert status.ok is False
    assert status.provider == "openai"


def test_preflight_auto_detect_openai_without_config(monkeypatch):
    monkeypatch.setattr(bh, "_detect_configured_providers", lambda: set())
    monkeypatch.setattr(bh, "_ollama_available", lambda: False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    status = bh.preflight_backend()
    assert status.ok is True
    assert status.provider == "openai"


def test_preflight_auto_detect_ollama_without_config(monkeypatch):
    monkeypatch.setattr(bh, "_detect_configured_providers", lambda: set())
    monkeypatch.setattr(bh, "_ollama_available", lambda: True)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    status = bh.preflight_backend()
    assert status.ok is True
    assert status.provider == "ollama"


def test_preflight_falls_back_to_openai_when_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(bh, "_detect_configured_providers", lambda: {"ollama"})
    monkeypatch.setattr(bh, "_ollama_available", lambda: False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    status = bh.preflight_backend()
    assert status.ok is True
    assert status.provider == "openai"
    assert status.details.get("fallback_from") == "ollama"


def test_apply_runtime_backend_sets_override_env(monkeypatch):
    monkeypatch.delenv("X3P_ACTIVE_BACKEND", raising=False)
    status = bh.BackendStatus(ok=True, provider="openai", message="ok", details={"fallback_from": "ollama"})

    warning = bh.apply_runtime_backend(status)
    assert os.getenv("X3P_ACTIVE_BACKEND") == "openai"
    assert "switched to OpenAI" in warning
