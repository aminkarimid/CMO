from x3p_content_manager.app import trend_intel as ti


def test_build_verified_trend_brief_fails_when_no_claim_is_verified(monkeypatch):
    monkeypatch.setattr(
        ti.social_trends_tool,
        "run",
        lambda **_kwargs: {"status": "ok", "data": [{"title": "Claim A"}, {"title": "Claim B"}]},
    )
    monkeypatch.setattr(
        ti.trend_verifier_tool,
        "run",
        lambda **_kwargs: {"status": "error", "message": "insufficient sources"},
    )

    brief = ti.build_verified_trend_brief(topic="x3p", audience="leaders", tone="clear")
    assert brief.ok is False
    assert "No trend claims passed strict verification" in brief.message
    assert len(brief.kept_claims) == 0


def test_build_verified_trend_brief_keeps_verified_claims(monkeypatch):
    monkeypatch.setattr(
        ti.social_trends_tool,
        "run",
        lambda **_kwargs: {"status": "ok", "data": [{"title": "Retention discussion is rising"}]},
    )
    monkeypatch.setattr(
        ti.trend_verifier_tool,
        "run",
        lambda **_kwargs: {
            "status": "ok",
            "data": [
                {"url": "https://example.com/a", "domain": "example.com", "title": "A", "published_at": "2026-02-01"},
                {"url": "https://example.org/b", "domain": "example.org", "title": "B", "published_at": "2026-02-02"},
            ],
        },
    )

    brief = ti.build_verified_trend_brief(topic="x3p", audience="leaders", tone="clear")
    assert brief.ok is True
    assert len(brief.kept_claims) == 1
    assert len(brief.citation_index) == 2
