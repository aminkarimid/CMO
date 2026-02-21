from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

import requests

OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"
REPORT_PATH = OUTPUTS_DIR / "analytics" / "x3p_quality_report.md"


@dataclass
class CheckResult:
    name: str
    file_path: Path
    passed: bool
    issues: List[str]

    def to_markdown(self) -> str:
        status = "✅ Pass" if self.passed else "❌ Needs Attention"
        lines = [f"### {self.name}", f"- File: `{self.file_path}`", f"- Status: {status}"]
        if self.issues:
            lines.append("- Findings:")
            for issue in self.issues:
                lines.append(f"  - {issue}")
        return "\n".join(lines)


def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def check_blog_post() -> CheckResult:
    path = OUTPUTS_DIR / "blog" / "x3p_blog_post.md"
    text = _load_text(path)
    issues: List[str] = []
    if not text:
        issues.append("File missing or empty.")
        return CheckResult("Blog Post", path, False, issues)

    if "### Opportunity Gap" not in text:
        issues.append("Missing required heading: ### Opportunity Gap")
    if "### How X3P Builds Good Jobs" not in text:
        issues.append("Missing required heading: ### How X3P Builds Good Jobs")
    if "### Outcomes & Partnerships" not in text:
        issues.append("Missing required heading: ### Outcomes & Partnerships")
    if "## Sources" not in text:
        issues.append("Missing ## Sources section.")
    if "Visit x3p.ai" not in text:
        issues.append("Missing CTA to Visit x3p.ai.")

    return CheckResult("Blog Post", path, not issues, issues)


def check_social_posts() -> CheckResult:
    path = OUTPUTS_DIR / "social" / "x3p_social_posts.md"
    text = _load_text(path)
    issues: List[str] = []
    if not text:
        issues.append("File missing or empty.")
        return CheckResult("Social Package", path, False, issues)

    for heading in (
        "## LinkedIn post 1",
        "## LinkedIn post 2",
        "## Facebook post 1",
        "## Facebook post 2",
        "## Instagram caption 1",
        "## Instagram caption 2",
    ):
        if heading not in text:
            issues.append(f"Missing section heading: {heading}")

    if "Visit x3p.ai" not in text:
        issues.append("Missing CTA to Visit x3p.ai.")

    return CheckResult("Social Package", path, not issues, issues)


def _extract_urls(text: str) -> List[str]:
    urls = re.findall(r"https?://[^\s)\]>]+", text or "")
    return list(dict.fromkeys(urls))


def check_links(limit: int = 10) -> CheckResult:
    path = OUTPUTS_DIR / "blog" / "x3p_blog_post.md"
    text = _load_text(path) + "\n" + _load_text(OUTPUTS_DIR / "social" / "x3p_social_posts.md")
    urls = _extract_urls(text)[:limit]
    issues: List[str] = []

    for url in urls:
        try:
            r = requests.get(url, timeout=6, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 X3P QA"})
            if not (200 <= r.status_code < 400):
                issues.append(f"{url} returned HTTP {r.status_code}")
        except Exception as e:
            issues.append(f"{url} failed: {e}")

    return CheckResult("Link Check", path, not issues, issues)


def check_citation_sanity() -> CheckResult:
    path = OUTPUTS_DIR / "blog" / "x3p_blog_post.md"
    text = _load_text(path)
    issues: List[str] = []
    if text:
        nums = re.findall(r"\b\d{1,3}(?:,\d{3})*%?\b", text)
        if nums and "## Sources" not in text:
            issues.append("Numeric claims found without sources section.")
    return CheckResult("Citation Sanity", path, not issues, issues)


def run_quality_checks(mode: str | None = None) -> List[CheckResult]:
    key = (mode or "all").strip().lower()
    if key == "run all":
        key = "all"

    checks_by_mode: dict[str, List[Callable[[], CheckResult]]] = {
        "all": [check_blog_post, check_social_posts, check_links, check_citation_sanity],
        "blog": [check_blog_post, check_links, check_citation_sanity],
        "social": [check_social_posts, check_links],
    }

    checks = checks_by_mode.get(key, checks_by_mode["all"])
    results = [fn() for fn in checks]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    lines = ["# X3P Content Quality Report", "", f"- Passed: {passed}/{total}"]
    for result in results:
        lines.append("")
        lines.append(result.to_markdown())
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    return results
