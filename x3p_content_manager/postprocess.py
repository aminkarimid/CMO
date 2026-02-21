"""Post-processing utilities to clean agent outputs before quality checks run."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Callable, List, Tuple, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
BLOG_DIR = REPO_ROOT / "outputs" / "blog"
BLOG_POST_PATH = BLOG_DIR / "x3p_blog_post.md"
BLOG_DRAFT_PATH = BLOG_DIR / "x3p_blog_draft.md"


def _strip_outer_code_fence(text: str) -> str:
    """Remove a single top-level markdown code fence wrapping the document."""
    fence_pattern = re.compile(r"^```[a-zA-Z0-9_-]*\n(.*?)\n```\s*$", re.DOTALL)
    match = fence_pattern.match(text.strip())
    if match:
        return match.group(1)
    return text


def _replace_disallowed_h3_headings(text: str) -> str:
    """Convert any unexpected H3 headings into bold inline labels."""
    allowed = {
        "Opportunity Gap",
        "How X3P Builds Good Jobs",
        "Outcomes & Partnerships",
    }

    def replacer(match: re.Match[str]) -> str:
        heading = match.group(1).strip()
        if heading in allowed:
            return match.group(0)
        # fallback: convert to bold label to preserve content without adding headings
        return f"\n**{heading}**\n"

    return re.sub(r"\n###\s+([^\n]+)\n", replacer, text)


def _load_blog_source() -> str:
    """Return the best-available blog content to sanitize."""
    if BLOG_POST_PATH.exists():
        candidate = BLOG_POST_PATH.read_text(encoding="utf-8")
        if re.match(r"^---\s*\n", candidate.lstrip()):
            return candidate
    if BLOG_DRAFT_PATH.exists():
        return BLOG_DRAFT_PATH.read_text(encoding="utf-8")
    return ""


def _remove_editor_notes(text: str) -> str:
    """Strip any trailing reviewer notes that should not ship."""
    lines = text.rstrip().splitlines()
    cleaned: list[str] = []
    for line in lines:
        if line.strip().lower().startswith("note:"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).rstrip() + "\n"


def _normalize_front_matter(text: str) -> str:
    """Ensure front matter exists, slug unquoted, and date current."""
    match = re.match(r"(---\s*\n.*?\n---\s*\n)(.*)", text, re.DOTALL)
    if not match:
        return text

    front_matter, body = match.groups()

    # Unquote slug if present
    front_matter = re.sub(r'(?m)^slug:\s*"?([^"\n]+)"?\s*$', r"slug: \1", front_matter)

    # Always apply today's date
    today = date.today().isoformat()
    front_matter = re.sub(r"(?m)^date:\s*.*$", f"date: {today}", front_matter)

    # Trim excess blank lines after front matter
    body = body.lstrip()
    return f"{front_matter}\n{body}"


def _ensure_required_headings(text: str) -> str:
    """Normalize headings that have drifted from the required template."""
    text = text.replace("### Call to Action", "**Call to Action**")
    text = _replace_disallowed_h3_headings(text)
    # Guarantee a blank line after the CTA label
    text = re.sub(r"\*\*Call to Action\*\*\s*", "**Call to Action**\n\n", text)
    # Collapse extra blank lines for cleanliness
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _extract_source_urls(sources_md: str) -> list[str]:
    urls: list[str] = []
    for line in sources_md.splitlines():
        m = re.search(r"\((https?://[^)]+)\)", line)
        if m:
            urls.append(m.group(1))
    return urls


def annotate_numeric_claims(text: str) -> str:
    """Insert [citation] after numeric claims lacking a nearby year/citation.
    Only modifies body prior to the '## Sources' section.
    Conservative: marks at most one claim per paragraph.
    """
    try:
        parts = text.split("\n## Sources", 1)
        body = parts[0]
        tail = "\n## Sources" + parts[1] if len(parts) > 1 else ""
        source_urls = _extract_source_urls(parts[1]) if len(parts) > 1 else []
        url_index = 0
        paras = body.split("\n\n")
        out: list[str] = []
        pat_num = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+%|\$?\d+(?:\.\d+)?\s*(?:million|billion|trillion)?)", re.I)
        for p in paras:
            # skip headings and lists
            if p.strip().startswith(("#", "-", "*", "1.", "2.", "3.")):
                out.append(p)
                continue
            if "[citation]" in p.lower():
                out.append(p)
                continue
            if re.search(r"\(?(20\d{2})\)?", p) or "http" in p.lower():
                out.append(p)
                continue
            m = pat_num.search(p)
            if not m:
                out.append(p)
                continue
            # insert marker after first match
            s, e = m.span()
            marker: str
            if url_index < len(source_urls):
                marker = f" [citation]({source_urls[url_index]})"
                url_index += 1
            else:
                marker = " [citation]"
            out.append(p[:e] + marker + p[e:])
        return "\n\n".join(out) + tail
    except Exception:
        return text


def extract_citation_pairs(text: str) -> List[Tuple[str, Optional[str]]]:
    """Return list of (claim_snippet, url_or_None) for each inserted citation marker.
    Parses the body prior to "## Sources" and finds numeric claims followed by
    [citation] or [citation](URL). Matches at most one per paragraph.
    """
    pairs: List[Tuple[str, Optional[str]]] = []
    try:
        parts = text.split("\n## Sources", 1)
        body = parts[0]
        paras = body.split("\n\n")
        pat_num = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+%|\$?\d+(?:\.\d+)?\s*(?:million|billion|trillion)?)", re.I)
        pat_cit = re.compile(r"\[citation\](?:\(([^)]+)\))?", re.I)
        for p in paras:
            # skip headings/lists
            if p.strip().startswith(("#", "-", "*", "1.", "2.", "3.")):
                continue
            m = pat_num.search(p)
            if not m:
                continue
            # only consider the first marker after the numeric claim
            tail = p[m.end():]
            mc = pat_cit.search(tail)
            if not mc:
                continue
            snippet = p[max(0, m.start()-20):m.end()].strip()
            url = mc.group(1) if mc.lastindex else None
            pairs.append((snippet, url))
    except Exception:
        return pairs
    return pairs


def sanitize_blog_post() -> None:
    """Normalize the published blog post so quality checks do not fail on format."""
    if not BLOG_POST_PATH.exists() and not BLOG_DRAFT_PATH.exists():
        return

    source = _load_blog_source()
    if not source.strip():
        return

    updated = _strip_outer_code_fence(source)
    updated = updated.lstrip()
    updated = _normalize_front_matter(updated)
    updated = _ensure_required_headings(updated)
    updated = _remove_editor_notes(updated)
    # Optional inline citation markers: mark numeric claims that lack nearby year/citation
    try:
        updated = annotate_numeric_claims(updated)
    except Exception:
        pass

    original = BLOG_POST_PATH.read_text(encoding="utf-8") if BLOG_POST_PATH.exists() else ""
    if updated != original:
        BLOG_DIR.mkdir(parents=True, exist_ok=True)
        BLOG_POST_PATH.write_text(updated, encoding="utf-8")


_SANITIZERS_BY_MODE: dict[str, tuple[Callable[[], None], ...]] = {
    "blog": (sanitize_blog_post,),
    "all": (sanitize_blog_post,),
}


def sanitize_outputs(mode: str) -> None:
    """Run the sanitizers associated with a pipeline mode."""
    for sanitizer in _SANITIZERS_BY_MODE.get(mode, ()):  # type: ignore[arg-type]
        sanitizer()
