"""Supabase publisher — writes pipeline output to X3P blog_posts and social_posts tables."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from x3p_content_manager.seo_schema import _parse_front_matter

logger = logging.getLogger(__name__)

_PLATFORM_HEADING_RE = re.compile(
    r"^##\s+(LinkedIn post \d+|Facebook post \d+|Instagram caption \d+)",
    re.IGNORECASE | re.MULTILINE,
)


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\s-]", "", (value or "").strip().lower())
    value = re.sub(r"[\s_-]+", "-", value).strip("-")
    return value or "post"


def _reading_time(content: str) -> int:
    words = len((content or "").split())
    return max(1, words // 200)


def _extract_hashtags(text: str) -> str:
    match = re.search(r"(?i)hashtags?:\s*(.+)", text)
    if match:
        return match.group(1).strip()
    return ""


def _extract_suggested_visual(text: str) -> str:
    match = re.search(r"(?i)suggested visual:\s*(.+)", text)
    if match:
        return match.group(1).strip()
    return ""


def _platform_key(heading: str) -> str:
    heading_lower = heading.lower()
    if "linkedin" in heading_lower:
        return "linkedin"
    if "facebook" in heading_lower:
        return "facebook"
    if "instagram" in heading_lower:
        return "instagram"
    return "other"


@dataclass
class BlogRecord:
    """Maps pipeline markdown output to blog_posts table columns."""

    title: str = ""
    slug: str = ""
    excerpt: str = ""
    content: str = ""
    date: str = ""
    image_url: Optional[str] = None
    author: str = "X3P Team"
    category: Optional[str] = None
    published: bool = True
    reading_time_minutes: int = 1
    meta_title: str = ""
    meta_description: str = ""


@dataclass
class SocialRecord:
    """Maps a single social post to social_posts table columns."""

    platform: str = ""
    content: str = ""
    hashtags: str = ""
    suggested_visual: str = ""
    published: bool = True


@dataclass
class PublishResult:
    """Result of a publish operation."""

    ok: bool = False
    blog_id: Optional[str] = None
    social_ids: list[str] = field(default_factory=list)
    error: Optional[str] = None
    slug: Optional[str] = None


def extract_blog_record(md_text: str) -> BlogRecord:
    """Parse pipeline markdown output into a BlogRecord for the blog_posts table."""
    fm, body = _parse_front_matter(md_text)
    title = str(fm.get("title") or "").strip() or "Untitled"
    slug = str(fm.get("slug") or "").strip() or _slugify(title)
    excerpt = str(fm.get("description") or "").strip()
    today = date.today().isoformat()
    post_date = str(fm.get("date") or today).strip()
    author = str(fm.get("author") or "X3P Team").strip()
    tags = fm.get("tags") or []
    category = tags[0] if isinstance(tags, list) and tags else None

    return BlogRecord(
        title=title,
        slug=slug,
        excerpt=excerpt,
        content=body.strip(),
        date=post_date,
        author=author,
        category=category,
        published=True,
        reading_time_minutes=_reading_time(body),
        meta_title=title,
        meta_description=excerpt,
    )


def parse_social_posts(social_md: str) -> list[SocialRecord]:
    """Parse social media markdown output into a list of SocialRecords."""
    posts: list[SocialRecord] = []
    sections = _PLATFORM_HEADING_RE.split(social_md)
    if len(sections) < 2:
        return posts

    # sections alternates: [preamble, heading1, body1, heading2, body2, ...]
    for i in range(1, len(sections), 2):
        heading = sections[i].strip()
        body = sections[i + 1].strip() if i + 1 < len(sections) else ""
        platform = _platform_key(heading)
        hashtags = _extract_hashtags(body)
        visual = _extract_suggested_visual(body)
        # Clean body: remove hashtag and visual lines for the content field
        content_lines = []
        for line in body.splitlines():
            if re.match(r"(?i)^hashtags?:\s*", line):
                continue
            if re.match(r"(?i)^suggested visual:\s*", line):
                continue
            content_lines.append(line)
        content = "\n".join(content_lines).strip()

        if content:
            posts.append(SocialRecord(
                platform=platform,
                content=content,
                hashtags=hashtags,
                suggested_visual=visual,
                published=True,
            ))
    return posts


class SupabasePublisher:
    """Publishes content to X3P Supabase backend."""

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
    ) -> None:
        self._url = url or os.getenv("SUPABASE_URL", "").strip()
        self._key = key or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        self._client: Any = None

    def is_configured(self) -> bool:
        return bool(self._url and self._key)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.is_configured():
            raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY.")
        from supabase import create_client

        self._client = create_client(self._url, self._key)
        return self._client

    def _ensure_unique_slug(self, slug: str) -> str:
        """Check for slug collision and append a suffix if needed."""
        client = self._get_client()
        base_slug = slug
        suffix = 0
        while True:
            check_slug = f"{base_slug}-{suffix}" if suffix else base_slug
            result = client.table("blog_posts").select("id").eq("slug", check_slug).execute()
            if not result.data:
                return check_slug
            suffix += 1
            if suffix > 50:
                # Fallback: use timestamp
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                return f"{base_slug}-{ts}"

    def publish_blog(self, md_text: str) -> PublishResult:
        """Parse markdown and insert into blog_posts. Returns PublishResult."""
        if not self.is_configured():
            return PublishResult(ok=False, error="Supabase not configured")
        try:
            record = extract_blog_record(md_text)
            record.slug = self._ensure_unique_slug(record.slug)
            client = self._get_client()
            row = {
                "slug": record.slug,
                "title": record.title,
                "excerpt": record.excerpt,
                "content": record.content,
                "date": record.date,
                "image_url": record.image_url,
                "author": record.author,
                "category": record.category,
                "published": record.published,
                "reading_time_minutes": record.reading_time_minutes,
                "meta_title": record.meta_title,
                "meta_description": record.meta_description,
            }
            result = client.table("blog_posts").insert(row).execute()
            blog_id = result.data[0]["id"] if result.data else None
            logger.info("Published blog post: slug=%s id=%s", record.slug, blog_id)
            return PublishResult(ok=True, blog_id=blog_id, slug=record.slug)
        except Exception as exc:
            logger.error("Failed to publish blog: %s", exc)
            return PublishResult(ok=False, error=str(exc))

    def publish_social(self, social_md: str, blog_post_id: Optional[str] = None) -> PublishResult:
        """Parse social markdown and insert into social_posts. Returns PublishResult."""
        if not self.is_configured():
            return PublishResult(ok=False, error="Supabase not configured")
        try:
            posts = parse_social_posts(social_md)
            if not posts:
                return PublishResult(ok=True, social_ids=[], error="No social posts parsed")
            client = self._get_client()
            rows = []
            for post in posts:
                row: dict[str, Any] = {
                    "platform": post.platform,
                    "content": post.content,
                    "hashtags": post.hashtags,
                    "suggested_visual": post.suggested_visual,
                    "published": post.published,
                }
                if blog_post_id:
                    row["blog_post_id"] = blog_post_id
                rows.append(row)
            result = client.table("social_posts").insert(rows).execute()
            ids = [r["id"] for r in (result.data or [])]
            logger.info("Published %d social posts linked to blog %s", len(ids), blog_post_id)
            return PublishResult(ok=True, blog_id=blog_post_id, social_ids=ids)
        except Exception as exc:
            logger.error("Failed to publish social posts: %s", exc)
            return PublishResult(ok=False, error=str(exc))

    def list_published(self, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch recent published blog posts."""
        if not self.is_configured():
            return []
        try:
            client = self._get_client()
            result = (
                client.table("blog_posts")
                .select("id, slug, title, date, published, created_at")
                .eq("published", True)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.error("Failed to list published posts: %s", exc)
            return []

    def health_check(self) -> tuple[bool, str]:
        """Quick connectivity check. Returns (ok, message)."""
        if not self.is_configured():
            return False, "SUPABASE_URL or SUPABASE_SERVICE_KEY not set"
        try:
            client = self._get_client()
            result = client.table("blog_posts").select("id").limit(1).execute()
            return True, "Supabase connection OK"
        except Exception as exc:
            return False, f"Supabase connection failed: {exc}"
