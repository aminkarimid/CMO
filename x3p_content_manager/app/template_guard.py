from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

try:
    import streamlit as st

    cache_data = st.cache_data
except Exception:  # pragma: no cover
    def cache_data(*_args, **_kwargs):  # type: ignore
        def _wrap(fn):
            return fn
        return _wrap


TASKS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "tasks.yaml"


@cache_data(show_spinner=False)
def extract_task_placeholders() -> set[str]:
    placeholders: set[str] = set()
    try:
        tasks_config = yaml.safe_load(TASKS_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        for task in tasks_config.values():
            desc = (task or {}).get("description", "") or ""
            placeholders.update(re.findall(r"\{([a-zA-Z0-9_]+)\}", desc))
    except Exception:
        return set()
    return placeholders


def build_template_safe_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    safe = dict(inputs or {})
    for key in extract_task_placeholders():
        safe.setdefault(key, "")
    return safe


def missing_template_vars(inputs: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in sorted(extract_task_placeholders()):
        if key not in inputs:
            missing.append(key)
    return missing


def extract_missing_template_var(msg: str) -> str | None:
    try:
        m = re.search(r"Template variable '([^']+)' not found in inputs dictionary", msg)
        if m:
            return m.group(1)
    except Exception:
        return None
    return None
