from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import yaml


def _parse_front_matter(md: str) -> Tuple[dict, str]:
    """Return (front_matter_dict, body_md). If none, returns ({}, md)."""
    md = md or ""
    if md.startswith("---\n"):
        end = md.find("\n---", 4)
        if end != -1:
            fm_text = md[4:end]
            body = md[end + 4 :].lstrip("\n")
            try:
                fm = yaml.safe_load(fm_text) or {}
            except Exception:
                fm = {}
            return fm, body
    return {}, md


def _coalesce(*vals: Optional[str], default: str = "") -> str:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def generate_seo_meta_block(md_text: str, *, site_origin: Optional[str] = None) -> str:
    fm, _ = _parse_front_matter(md_text)
    title = _coalesce(fm.get("title"), default="X3P Blog")
    description = _coalesce(fm.get("description"), default="Visit x3p.ai — expanding access to good jobs.")
    slug = _coalesce(fm.get("slug"), default="")
    date = _coalesce(fm.get("date"), default=datetime.now().strftime("%Y-%m-%d"))
    tags = fm.get("tags") or []

    origin = _coalesce(site_origin, os.getenv("X3P_SITE_ORIGIN"), default="https://x3p.ai")
    base_path = "/blog/" + slug if slug else "/blog"
    canonical = origin.rstrip("/") + base_path

    og_image = _coalesce(os.getenv("X3P_OG_IMAGE"), default=origin.rstrip("/") + "/static/og-default.png")
    twitter_handle = _coalesce(os.getenv("X3P_TWITTER_HANDLE"), default="@x3p_ai")

    meta_lines = [
        f'<link rel="canonical" href="{canonical}" />',
        f'<meta name="description" content="{description}" />',
        f'<meta property="og:title" content="{title}" />',
        f'<meta property="og:description" content="{description}" />',
        f'<meta property="og:type" content="article" />',
        f'<meta property="og:url" content="{canonical}" />',
        f'<meta property="og:image" content="{og_image}" />',
        f'<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:site" content="{twitter_handle}" />',
        f'<meta name="twitter:title" content="{title}" />',
        f'<meta name="twitter:description" content="{description}" />',
        f'<meta name="twitter:image" content="{og_image}" />',
    ]

    # JSON-LD Article + Organization
    article_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "datePublished": date,
        "dateModified": date,
        "author": [{"@type": "Organization", "name": "X3P"}],
        "publisher": {
            "@type": "Organization",
            "name": "X3P",
            "url": origin,
            "logo": {
                "@type": "ImageObject",
                "url": origin.rstrip("/") + "/static/logo.png",
            },
        },
        "mainEntityOfPage": canonical,
        "keywords": ", ".join(tags) if isinstance(tags, list) else str(tags),
    }
    org_ld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "X3P",
        "url": origin,
    }
    meta_lines.append('<script type="application/ld+json">' + json.dumps(article_ld, ensure_ascii=False) + "</script>")
    meta_lines.append('<script type="application/ld+json">' + json.dumps(org_ld, ensure_ascii=False) + "</script>")

    return "\n".join(meta_lines) + "\n"


def save_seo_meta(md_text: str, outputs_dir: str = "outputs/seo") -> Optional[str]:
    try:
        Path(outputs_dir).mkdir(parents=True, exist_ok=True)
        html = generate_seo_meta_block(md_text)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(outputs_dir) / f"x3p_seo_meta_{ts}.html"
        path.write_text(html, encoding="utf-8")
        return str(path)
    except Exception:
        return None

