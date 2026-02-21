from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
import yaml

AGENTS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "agents.yaml"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OLLAMA_MODEL = "ollama/llama3.1:8b"


@dataclass
class BackendStatus:
    ok: bool
    provider: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def _ollama_base_url() -> str:
    return str(os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")


def _ollama_available() -> bool:
    try:
        resp = requests.get(f"{_ollama_base_url()}/api/tags", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _openai_available() -> bool:
    return bool(str(os.getenv("OPENAI_API_KEY", "")).strip())


def _detect_configured_providers() -> set[str]:
    providers: set[str] = set()
    try:
        agents = yaml.safe_load(AGENTS_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        for agent in agents.values():
            llm = str((agent or {}).get("llm") or "").strip().lower()
            if not llm:
                continue
            if llm.startswith("ollama/") or "ollama" in llm:
                providers.add("ollama")
            elif llm.startswith("gpt") or llm.startswith("openai/") or "openai" in llm:
                providers.add("openai")
            elif llm.startswith("claude") or "anthropic" in llm:
                providers.add("anthropic")
    except Exception:
        pass
    return providers


def preflight_backend() -> BackendStatus:
    providers = _detect_configured_providers()
    openai_ready = _openai_available()
    ollama_ready = _ollama_available()

    if not providers:
        # Auto-detect mode when llm fields are absent.
        if openai_ready:
            return BackendStatus(True, "openai", "OpenAI credentials detected.", {"providers": ["openai"]})
        if ollama_ready:
            return BackendStatus(True, "ollama", "Ollama is reachable.", {"providers": ["ollama"]})
        return BackendStatus(
            False,
            "none",
            f"No usable backend found. Configure OPENAI_API_KEY or start Ollama on {_ollama_base_url()}.",
            {"providers": []},
        )

    details: dict[str, Any] = {
        "providers": sorted(providers),
        "openai_key": openai_ready,
        "ollama_reachable": ollama_ready,
    }

    # Configured backend is ready.
    if "openai" in providers and openai_ready:
        if "ollama" in providers and ollama_ready:
            return BackendStatus(True, "mixed", "Backend preflight passed (mixed).", details)
        if "ollama" in providers and not ollama_ready:
            details["fallback_from"] = "ollama"
            return BackendStatus(True, "openai", "Ollama is unavailable; using OpenAI.", details)
        return BackendStatus(True, "openai", "Backend preflight passed (openai).", details)

    if "ollama" in providers and ollama_ready:
        if "openai" in providers and not openai_ready:
            details["fallback_from"] = "openai"
            return BackendStatus(True, "ollama", "OPENAI_API_KEY missing; using Ollama.", details)
        return BackendStatus(True, "ollama", "Backend preflight passed (ollama).", details)

    # Configured backend failed; allow one-side auto-fallback.
    if "ollama" in providers and not ollama_ready and openai_ready:
        details["fallback_from"] = "ollama"
        return BackendStatus(True, "openai", "Ollama is unavailable; using OpenAI.", details)

    if "openai" in providers and not openai_ready and ollama_ready:
        details["fallback_from"] = "openai"
        return BackendStatus(True, "ollama", "OPENAI_API_KEY missing; using Ollama.", details)

    if "openai" in providers and not openai_ready and "ollama" not in providers:
        return BackendStatus(False, "openai", "OPENAI_API_KEY is missing for configured OpenAI models.", details)

    if "ollama" in providers and not ollama_ready and "openai" not in providers:
        return BackendStatus(False, "ollama", f"Ollama is not reachable at {_ollama_base_url()}.", details)

    return BackendStatus(
        False,
        "none",
        f"No usable backend found. Configure OPENAI_API_KEY or start Ollama on {_ollama_base_url()}.",
        details,
    )


def apply_runtime_backend(status: BackendStatus) -> str | None:
    if not status.ok:
        os.environ.pop("X3P_ACTIVE_BACKEND", None)
        return None

    provider = status.provider
    if provider == "mixed":
        provider = "openai" if _openai_available() else "ollama"

    if provider == "openai":
        os.environ["X3P_ACTIVE_BACKEND"] = "openai"
        os.environ.setdefault("X3P_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    elif provider == "ollama":
        os.environ["X3P_ACTIVE_BACKEND"] = "ollama"
        os.environ.setdefault("X3P_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)

    fallback_from = str(status.details.get("fallback_from", "")).strip().lower()
    if fallback_from and fallback_from != provider:
        names = {"openai": "OpenAI", "ollama": "Ollama"}
        from_name = names.get(fallback_from, fallback_from)
        to_name = names.get(provider, provider)
        return f"{from_name} was unavailable; switched to {to_name} automatically."
    return None
