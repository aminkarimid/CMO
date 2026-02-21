from __future__ import annotations

from typing import Any

import streamlit as st


class LiveProgress:
    """Simple human-readable progress renderer for minimal UI."""

    FRIENDLY = {
        "Blog": "Draft blog",
        "Blog (Re-Edit)": "Refine blog",
        "Social": "Adapt social posts",
        "Fact-check": "Verify claims",
        "Brand Check": "Check brand fit",
        "Run All": "Complete package",
    }

    def __init__(self, title: str = "Run Progress") -> None:
        self._box = st.expander(title, expanded=True)
        self._placeholder = self._box.empty()
        self._rows: list[dict[str, Any]] = []

    def start(self, label: str, agent: str | None = None) -> None:
        self._rows.append({"label": label, "agent": agent or "", "status": "running", "note": ""})
        self._render()

    def done(self, label: str, ok: bool = True, note: str | None = None, duration_ms: int | None = None) -> None:
        for row in self._rows:
            if row["label"] == label and row["status"] == "running":
                row["status"] = "done" if ok else "failed"
                row["note"] = note or ""
                if duration_ms:
                    suffix = f"{duration_ms / 1000:.1f}s"
                    row["note"] = f"{row['note']} · {suffix}".strip(" ·")
                break
        self._render()

    def _render(self) -> None:
        icons = {"running": "⏳", "done": "✅", "failed": "❌"}
        lines = ["#### Progress"]
        for row in self._rows:
            label = self.FRIENDLY.get(row["label"], row["label"])
            text = f"{icons.get(row['status'], '•')} **{label}**"
            if row.get("note"):
                text += f" · {row['note']}"
            lines.append(f"- {text}")
        self._placeholder.markdown("\n".join(lines))
