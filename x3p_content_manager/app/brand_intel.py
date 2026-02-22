from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from x3p_content_manager.tools import x3p_site_snapshot_tool

BRAND_INTEL_DIR = Path("runs") / "brand_intel"
SNAPSHOT_PATH = BRAND_INTEL_DIR / "latest.json"
BRIEF_PATH = BRAND_INTEL_DIR / "brief_latest.json"


@dataclass
class BrandSnapshot:
    ok: bool
    refreshed: bool
    captured_at: str
    age_hours: float
    source_count: int
    snapshot_path: str
    brief_path: str
    brief: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["age_hours"] = round(float(self.age_hours), 2)
        return data


def _ensure_brand_dir() -> None:
    BRAND_INTEL_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _age_hours(captured_at: str) -> float:
    dt = _parse_iso(captured_at)
    if not dt:
        return 10_000.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _distill_brief(snapshot_payload: dict[str, Any]) -> dict[str, Any]:
    rows = snapshot_payload.get("data") if isinstance(snapshot_payload, dict) else []
    rows = rows if isinstance(rows, list) else []
    messages: list[str] = []
    offerings: list[str] = []
    audiences: list[str] = []
    tone_notes = [
        "evidence-based",
        "human-centered",
        "practical",
    ]
    citations: list[dict[str, Any]] = []

    for idx, row in enumerate(rows, start=1):
        text = str((row or {}).get("text") or "")
        title = str((row or {}).get("title") or "")
        url = str((row or {}).get("url") or "")
        evidence_id = f"E{idx:03d}"
        if url:
            citations.append({"evidence_id": evidence_id, "url": url, "note": title[:120]})

        lower = text.lower()
        if "good jobs" in lower and "good jobs" not in messages:
            messages.append("X3P focuses on building and scaling good jobs pathways.")
        if ("partnership" in lower or "partner" in lower) and "Partnership-oriented model with employers and operators." not in messages:
            messages.append("Partnership-oriented model with employers and operators.")
        if "care" in lower and "x3p operates in the care economy." not in messages:
            messages.append("X3P operates in the care economy.")
        if "platform" in lower and "X3P provides a platform-enabled workflow for workforce outcomes." not in offerings:
            offerings.append("X3P provides a platform-enabled workflow for workforce outcomes.")
        if ("employer" in lower or "provider" in lower) and "Provider and employer leaders" not in audiences:
            audiences.append("Provider and employer leaders")
        if ("caregiver" in lower or "worker" in lower) and "Workers and caregivers" not in audiences:
            audiences.append("Workers and caregivers")

    if not messages:
        messages.append("X3P is a care-economy platform focused on quality jobs and workforce outcomes.")
    if not offerings:
        offerings.append("Good-jobs pathway enablement for care workforce partners.")
    if not audiences:
        audiences.extend(["Provider leaders", "Care workforce participants"])

    proof_points = [
        {
            "claim": "Use site-verified messaging and avoid unsupported numeric claims.",
            "evidence_id": citations[0]["evidence_id"] if citations else "",
        }
    ]

    return {
        "captured_at": _now_iso(),
        "source_count": len(rows),
        "core_messages": messages[:8],
        "offerings": offerings[:8],
        "audiences": audiences[:8],
        "tone_notes": tone_notes,
        "proof_points": proof_points,
        "do_not_say": [
            "Unverified performance guarantees",
            "Fabricated partner names",
            "Unsupported numerical outcomes",
        ],
        "citation_index": citations[:20],
    }


def load_brand_snapshot() -> BrandSnapshot:
    _ensure_brand_dir()
    brief = _read_json(BRIEF_PATH)
    captured_at = str(brief.get("captured_at") or "")
    if not captured_at:
        captured_at = "1970-01-01T00:00:00+00:00"
    return BrandSnapshot(
        ok=bool(brief),
        refreshed=False,
        captured_at=captured_at,
        age_hours=_age_hours(captured_at),
        source_count=int(brief.get("source_count") or 0),
        snapshot_path=str(SNAPSHOT_PATH),
        brief_path=str(BRIEF_PATH),
        brief=brief,
        warnings=[] if brief else ["No brand snapshot available yet."],
    )


def refresh_brand_snapshot(force: bool = False, max_age_hours: int = 24) -> BrandSnapshot:
    _ensure_brand_dir()

    current = load_brand_snapshot()
    if current.ok and not force and current.age_hours <= float(max_age_hours):
        current.refreshed = False
        return current

    warnings: list[str] = []
    snapshot_result = x3p_site_snapshot_tool.run(include_sitemap=True, max_pages=8)
    if str(snapshot_result.get("status", "")).lower() != "ok":
        if current.ok:
            current.warnings.append("Brand snapshot refresh failed; using previous snapshot.")
            return current
        raise RuntimeError(f"Brand snapshot refresh failed: {snapshot_result.get('message', 'unknown error')}")

    brief = _distill_brief(snapshot_result)
    _write_json(SNAPSHOT_PATH, snapshot_result)
    _write_json(BRIEF_PATH, brief)

    return BrandSnapshot(
        ok=True,
        refreshed=True,
        captured_at=str(brief.get("captured_at") or _now_iso()),
        age_hours=0.0,
        source_count=int(brief.get("source_count") or 0),
        snapshot_path=str(SNAPSHOT_PATH),
        brief_path=str(BRIEF_PATH),
        brief=brief,
        warnings=warnings,
    )
