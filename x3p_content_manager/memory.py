from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_BASE_DIR = Path(__file__).resolve().parents[1]
_RUNS_DIR = _BASE_DIR / "runs"
_MEMORY_PATH = _RUNS_DIR / "memory.jsonl"


def _ensure_runs_dir() -> None:
    _RUNS_DIR.mkdir(exist_ok=True)


def _truncate_text(text: str, limit: int = 280) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def append_memory_entry(entry: Dict[str, Any]) -> None:
    record = dict(entry)
    record.setdefault("timestamp", datetime.utcnow().isoformat())
    _ensure_runs_dir()
    with _MEMORY_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_memory(limit: Optional[int] = 10) -> List[Dict[str, Any]]:
    if not _MEMORY_PATH.exists():
        return []
    entries: List[Dict[str, Any]] = []
    try:
        with _MEMORY_PATH.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        entries.append(entry)
        if limit is not None and len(entries) >= limit:
            break
    return entries


def remember_run(pipeline: str, inputs: Optional[Dict[str, Any]], text: Optional[str] = None) -> None:
    if not inputs:
        return
    entry: Dict[str, Any] = {
        "pipeline": pipeline,
        "topic": inputs.get("topic", ""),
        "audience": inputs.get("audience", ""),
        "tone": inputs.get("tone", ""),
        "content_type": inputs.get("content_type", ""),
        "key_facts": list(inputs.get("key_facts", [])) if isinstance(inputs.get("key_facts"), list) else [],
    }
    brief = inputs.get("brief") or {}
    if isinstance(brief, dict):
        entry["brief_objective"] = brief.get("objective", "")
    brand = inputs.get("brand_guide") or {}
    if isinstance(brand, dict):
        entry["brand_voice"] = brand.get("voice", [])
    if text:
        entry["summary"] = _truncate_text(text)
    append_memory_entry(entry)


__all__ = ["append_memory_entry", "load_memory", "remember_run"]
