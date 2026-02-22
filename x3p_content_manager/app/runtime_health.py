from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from x3p_content_manager.app.backend_health import BackendStatus, preflight_backend
from x3p_content_manager.tools import USER_AGENT, brand_retriever_tool


@dataclass
class HealthCheck:
    name: str
    ok: bool
    message: str
    critical: bool = True
    latency_ms: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.latency_ms is not None:
            data["latency_ms"] = round(self.latency_ms, 2)
        return data


@dataclass
class HealthReport:
    ok: bool
    message: str
    checked_at: str
    backend: BackendStatus
    checks: list[HealthCheck]
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "checked_at": self.checked_at,
            "backend": {
                "ok": self.backend.ok,
                "provider": self.backend.provider,
                "message": self.backend.message,
                "details": self.backend.details,
            },
            "checks": [check.to_dict() for check in self.checks],
            "details": self.details,
        }


def _probe_tavily(timeout_sec: int = 6) -> HealthCheck:
    key = str(os.getenv("TAVILY_API_KEY", "")).strip()
    if not key:
        return HealthCheck(
            name="tavily_tool",
            ok=False,
            message="TAVILY_API_KEY is missing.",
            critical=True,
            details={"failure_reason": "missing_tavily_key"},
        )

    start = time.perf_counter()
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            json={
                "query": "x3p.ai workforce",
                "num_results": 1,
                "search_depth": "basic",
                "include_domains": ["x3p.ai"],
            },
            timeout=timeout_sec,
        )
        latency = (time.perf_counter() - start) * 1000
        if resp.status_code != 200:
            return HealthCheck(
                name="tavily_tool",
                ok=False,
                message=f"Tavily returned HTTP {resp.status_code}.",
                critical=True,
                latency_ms=latency,
                details={"failure_reason": f"http_{resp.status_code}"},
            )

        payload = resp.json() if resp.content else {}
        results = payload.get("results") if isinstance(payload, dict) else None
        result_count = len(results) if isinstance(results, list) else 0
        return HealthCheck(
            name="tavily_tool",
            ok=True,
            message="Tavily probe succeeded.",
            critical=True,
            latency_ms=latency,
            details={"result_count": result_count},
        )
    except requests.Timeout:
        latency = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="tavily_tool",
            ok=False,
            message="Tavily probe timed out.",
            critical=True,
            latency_ms=latency,
            details={"failure_reason": "timeout"},
        )
    except Exception as exc:
        latency = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="tavily_tool",
            ok=False,
            message=f"Tavily probe failed: {type(exc).__name__}",
            critical=True,
            latency_ms=latency,
            details={"failure_reason": "connection_error", "error": str(exc)},
        )


def _probe_brand_retriever() -> HealthCheck:
    start = time.perf_counter()
    try:
        result = brand_retriever_tool.run(query="x3p brand", top_k=1)
        latency = (time.perf_counter() - start) * 1000
        ok = isinstance(result, dict) and str(result.get("status", "")).lower() == "ok"
        message = "Brand retriever probe succeeded." if ok else str((result or {}).get("message", "Brand retriever probe failed."))
        return HealthCheck(
            name="brand_retriever_tool",
            ok=ok,
            message=message,
            critical=False,
            latency_ms=latency,
        )
    except Exception as exc:
        latency = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="brand_retriever_tool",
            ok=False,
            message=f"Brand retriever probe failed: {type(exc).__name__}",
            critical=False,
            latency_ms=latency,
            details={"error": str(exc)},
        )


def _probe_x3p_site(timeout_sec: int = 6) -> HealthCheck:
    start = time.perf_counter()
    try:
        resp = requests.get(
            "https://x3p.ai",
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_sec,
        )
        latency = (time.perf_counter() - start) * 1000
        if 200 <= resp.status_code < 400:
            return HealthCheck(
                name="x3p_site",
                ok=True,
                message="x3p.ai is reachable.",
                critical=True,
                latency_ms=latency,
                details={"http_status": resp.status_code},
            )
        return HealthCheck(
            name="x3p_site",
            ok=False,
            message=f"x3p.ai returned HTTP {resp.status_code}.",
            critical=True,
            latency_ms=latency,
            details={"http_status": resp.status_code, "failure_reason": "unexpected_status"},
        )
    except requests.Timeout:
        latency = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="x3p_site",
            ok=False,
            message="x3p.ai probe timed out.",
            critical=True,
            latency_ms=latency,
            details={"failure_reason": "timeout"},
        )
    except Exception as exc:
        latency = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="x3p_site",
            ok=False,
            message=f"x3p.ai probe failed: {type(exc).__name__}",
            critical=True,
            latency_ms=latency,
            details={"failure_reason": "connection_error", "error": str(exc)},
        )


def run_preflight_checks() -> HealthReport:
    checked_at = datetime.now(timezone.utc).isoformat()
    backend_status = preflight_backend()
    checks: list[HealthCheck] = []

    if backend_status.ok:
        checks.extend(
            [
                _probe_tavily(),
                _probe_x3p_site(),
                _probe_brand_retriever(),
            ]
        )

    critical_failures = [check for check in checks if check.critical and not check.ok]
    tool_health = {check.name: check.to_dict() for check in checks}
    backend_status.details["tool_health"] = tool_health

    if not backend_status.ok:
        message = backend_status.message
        ok = False
    elif critical_failures:
        names = ", ".join(check.name for check in critical_failures)
        message = f"Critical health checks failed: {names}."
        ok = False
    else:
        message = "System health checks passed."
        ok = True

    return HealthReport(
        ok=ok,
        message=message,
        checked_at=checked_at,
        backend=backend_status,
        checks=checks,
        details={
            "critical_failures": [check.name for check in critical_failures],
            "tool_health": tool_health,
        },
    )
