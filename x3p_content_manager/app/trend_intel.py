from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from x3p_content_manager.tools import social_trends_tool, trend_verifier_tool


@dataclass
class TrendBrief:
    ok: bool
    message: str
    generated_at: str
    trend_window_days: int
    kept_claims: list[dict[str, Any]] = field(default_factory=list)
    dropped_claims: list[dict[str, Any]] = field(default_factory=list)
    citation_index: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_claims(trends_payload: dict[str, Any], limit: int = 6) -> list[str]:
    rows = trends_payload.get("data") if isinstance(trends_payload, dict) else []
    claims: list[str] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        title = str((row or {}).get("title") or "").strip()
        snippet = str((row or {}).get("snippet") or "").strip()
        candidate = title or snippet
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(candidate[:240])
        if len(claims) >= limit:
            break
    return claims


def build_verified_trend_brief(
    *,
    topic: str,
    audience: str,
    tone: str,
    trend_window_days: int = 7,
    min_sources: int = 2,
    max_claims: int = 4,
) -> TrendBrief:
    trend_result = social_trends_tool.run(include_platforms="web,reddit", limit=10, region="united-states")
    if str(trend_result.get("status", "")).lower() != "ok":
        return TrendBrief(
            ok=False,
            message=f"Trend sourcing failed: {trend_result.get('message', 'unknown error')}",
            generated_at=_now_iso(),
            trend_window_days=int(trend_window_days),
        )

    candidates = _candidate_claims(trend_result, limit=max_claims * 2)
    kept_claims: list[dict[str, Any]] = []
    dropped_claims: list[dict[str, Any]] = []
    citation_index: list[dict[str, Any]] = []

    evidence_counter = 1
    for claim in candidates:
        verify = trend_verifier_tool.run(
            query=f"{topic} {claim}",
            region="united-states",
            recency_days=int(trend_window_days),
            min_sources=int(min_sources),
            max_results=8,
        )
        if str(verify.get("status", "")).lower() != "ok":
            dropped_claims.append({"claim": claim, "reason": verify.get("message", "verification failed")})
            continue

        evidence_rows = verify.get("data", [])
        ids: list[str] = []
        for row in evidence_rows:
            evidence_id = f"T{evidence_counter:03d}"
            evidence_counter += 1
            ids.append(evidence_id)
            citation_index.append(
                {
                    "evidence_id": evidence_id,
                    "url": row.get("url", ""),
                    "domain": row.get("domain", ""),
                    "title": row.get("title", ""),
                    "published_at": row.get("published_at", ""),
                }
            )

        kept_claims.append(
            {
                "claim": claim,
                "evidence_ids": ids,
                "rationale": f"Relevant to {audience} with a {tone} framing and verified multi-source signal.",
            }
        )
        if len(kept_claims) >= max_claims:
            break

    if not kept_claims:
        return TrendBrief(
            ok=False,
            message="No trend claims passed strict verification (minimum 2 independent sources).",
            generated_at=_now_iso(),
            trend_window_days=int(trend_window_days),
            kept_claims=[],
            dropped_claims=dropped_claims,
            citation_index=[],
        )

    return TrendBrief(
        ok=True,
        message=f"Verified {len(kept_claims)} trend claims.",
        generated_at=_now_iso(),
        trend_window_days=int(trend_window_days),
        kept_claims=kept_claims,
        dropped_claims=dropped_claims,
        citation_index=citation_index,
    )
