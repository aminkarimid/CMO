import json
from pathlib import Path

from x3p_content_manager.app import brand_intel as bi


def _set_paths(monkeypatch, tmp_path: Path) -> None:
    brand_dir = tmp_path / "runs" / "brand_intel"
    monkeypatch.setattr(bi, "BRAND_INTEL_DIR", brand_dir)
    monkeypatch.setattr(bi, "SNAPSHOT_PATH", brand_dir / "latest.json")
    monkeypatch.setattr(bi, "BRIEF_PATH", brand_dir / "brief_latest.json")


def test_refresh_brand_snapshot_writes_files(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)

    def _ok_snapshot(**_kwargs):  # type: ignore[no-untyped-def]
        return {
            "status": "ok",
            "data": [
                {"url": "https://x3p.ai", "title": "X3P", "text": "X3P builds good jobs in care."},
                {"url": "https://x3p.ai/about", "title": "About", "text": "Partner pathways for providers."},
            ],
        }

    monkeypatch.setattr(bi.x3p_site_snapshot_tool, "run", _ok_snapshot)
    snap = bi.refresh_brand_snapshot(force=True, max_age_hours=24)

    assert snap.ok is True
    assert snap.refreshed is True
    assert snap.source_count == 2
    assert Path(snap.snapshot_path).exists()
    assert Path(snap.brief_path).exists()


def test_refresh_brand_snapshot_skips_when_fresh(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)
    bi.BRAND_INTEL_DIR.mkdir(parents=True, exist_ok=True)
    brief = {
        "captured_at": bi._now_iso(),
        "source_count": 1,
        "core_messages": ["stub"],
    }
    bi.BRIEF_PATH.write_text(json.dumps(brief), encoding="utf-8")

    called = {"n": 0}

    def _should_not_call(**_kwargs):  # type: ignore[no-untyped-def]
        called["n"] += 1
        return {"status": "error", "message": "should not call"}

    monkeypatch.setattr(bi.x3p_site_snapshot_tool, "run", _should_not_call)
    snap = bi.refresh_brand_snapshot(force=False, max_age_hours=24)

    assert snap.ok is True
    assert snap.refreshed is False
    assert called["n"] == 0


def test_refresh_brand_snapshot_force_refreshes_even_if_fresh(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)
    bi.BRAND_INTEL_DIR.mkdir(parents=True, exist_ok=True)
    brief = {
        "captured_at": bi._now_iso(),
        "source_count": 1,
        "core_messages": ["stub"],
    }
    bi.BRIEF_PATH.write_text(json.dumps(brief), encoding="utf-8")

    called = {"n": 0}

    def _ok_snapshot(**_kwargs):  # type: ignore[no-untyped-def]
        called["n"] += 1
        return {"status": "ok", "data": [{"url": "https://x3p.ai", "title": "X3P", "text": "good jobs"}]}

    monkeypatch.setattr(bi.x3p_site_snapshot_tool, "run", _ok_snapshot)
    snap = bi.refresh_brand_snapshot(force=True, max_age_hours=24)

    assert snap.ok is True
    assert snap.refreshed is True
    assert called["n"] == 1
