from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
import yaml

AGENTS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "agents.yaml"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
OPENAI_BASE_URL = "https://api.openai.com/v1"


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


def _openai_key() -> str:
    return str(os.getenv("OPENAI_API_KEY", "")).strip()


def _normalize_model_name(model: str | None) -> str:
    raw = str(model or DEFAULT_OPENAI_MODEL).strip()
    if raw.lower().startswith("openai/"):
        return raw.split("/", 1)[1].strip() or DEFAULT_OPENAI_MODEL
    return raw or DEFAULT_OPENAI_MODEL


def _preflight_generation_check_enabled() -> bool:
    raw = str(os.getenv("X3P_PREFLIGHT_GENERATION_CHECK", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


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
            if llm.startswith("gpt") or llm.startswith("openai/") or "openai" in llm:
                providers.add("openai")
    except Exception:
        pass
    return providers


def _ping_openai_model(model: str, timeout_sec: int = 6) -> tuple[bool, float | None, str | None]:
    key = _openai_key()
    if not key:
        return False, None, "missing_api_key"
    start = time.perf_counter()
    try:
        resp = requests.get(
            f"{OPENAI_BASE_URL}/models/{model}",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=timeout_sec,
        )
    except requests.Timeout:
        elapsed = (time.perf_counter() - start) * 1000
        return False, elapsed, "openai_timeout"
    except requests.RequestException:
        elapsed = (time.perf_counter() - start) * 1000
        return False, elapsed, "openai_connection_error"

    elapsed = (time.perf_counter() - start) * 1000
    if resp.status_code == 200:
        return True, elapsed, None
    if resp.status_code in {401, 403}:
        return False, elapsed, "invalid_api_key_or_permission"
    if resp.status_code == 404:
        return False, elapsed, "model_not_found_or_not_allowed"
    return False, elapsed, f"openai_http_{resp.status_code}"


def _ping_openai_generation(model: str, timeout_sec: int = 8) -> tuple[bool, float | None, str | None]:
    key = _openai_key()
    if not key:
        return False, None, "missing_api_key"
    start = time.perf_counter()
    try:
        resp = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "healthcheck"}],
                "max_tokens": 1,
                "temperature": 0,
            },
            timeout=timeout_sec,
        )
    except requests.Timeout:
        elapsed = (time.perf_counter() - start) * 1000
        return False, elapsed, "openai_generation_timeout"
    except requests.RequestException:
        elapsed = (time.perf_counter() - start) * 1000
        return False, elapsed, "openai_generation_connection_error"

    elapsed = (time.perf_counter() - start) * 1000
    if resp.status_code == 200:
        return True, elapsed, None
    if resp.status_code == 429:
        try:
            payload = resp.json() or {}
            err = (payload.get("error") or {}) if isinstance(payload, dict) else {}
            code = str(err.get("code") or "").strip().lower()
            msg = str(err.get("message") or "").strip().lower()
            if code == "insufficient_quota" or "exceeded your current quota" in msg:
                return False, elapsed, "insufficient_quota"
        except Exception:
            pass
        return False, elapsed, "openai_rate_limit_or_quota"
    if resp.status_code in {401, 403}:
        return False, elapsed, "invalid_api_key_or_permission"
    if resp.status_code == 404:
        return False, elapsed, "model_not_found_or_not_allowed"
    return False, elapsed, f"openai_generation_http_{resp.status_code}"


def preflight_backend() -> BackendStatus:
    configured_providers = sorted(_detect_configured_providers())
    model = _normalize_model_name(os.getenv("X3P_OPENAI_MODEL", DEFAULT_OPENAI_MODEL))
    ping_ok, ping_ms, failure_reason = _ping_openai_model(model=model, timeout_sec=6)

    details: dict[str, Any] = {
        "provider": "openai",
        "configured_providers": configured_providers,
        "openai_key": bool(_openai_key()),
        "llm_model": model,
        "llm_ping_ms": round(ping_ms, 2) if ping_ms is not None else None,
        "generation_ping_ms": None,
        "ollama_reachable": _ollama_available(),
        "failure_reason": failure_reason,
        "tool_health": {},
    }

    if not details["openai_key"]:
        return BackendStatus(
            ok=False,
            provider="openai",
            message="OPENAI_API_KEY is required for CMO runtime.",
            details=details,
        )
    if not ping_ok:
        return BackendStatus(
            ok=False,
            provider="openai",
            message=f"OpenAI model check failed ({failure_reason}).",
            details=details,
        )

    if _preflight_generation_check_enabled():
        gen_ok, gen_ms, gen_failure = _ping_openai_generation(model=model, timeout_sec=8)
        details["generation_ping_ms"] = round(gen_ms, 2) if gen_ms is not None else None
        if not gen_ok:
            details["failure_reason"] = gen_failure
            return BackendStatus(
                ok=False,
                provider="openai",
                message=f"OpenAI generation check failed ({gen_failure}).",
                details=details,
            )

    return BackendStatus(
        ok=True,
        provider="openai",
        message="Backend preflight passed (openai).",
        details=details,
    )


def apply_runtime_backend(status: BackendStatus) -> str | None:
    if not status.ok:
        os.environ.pop("X3P_ACTIVE_BACKEND", None)
        return None

    model = _normalize_model_name(status.details.get("llm_model"))
    os.environ["X3P_ACTIVE_BACKEND"] = "openai"
    os.environ["X3P_OPENAI_MODEL"] = model
    configured = [str(p).lower() for p in status.details.get("configured_providers", [])]
    if configured and configured != ["openai"]:
        return "OpenAI primary policy is enabled; non-OpenAI providers were ignored."
    return None
