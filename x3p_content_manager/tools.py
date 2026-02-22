from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import requests
from crewai.tools import BaseTool, EnvVar
from pydantic import BaseModel

USER_AGENT = os.getenv(
    "X3P_HTTP_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)
CACHE_TTL = int(os.getenv("X3P_TOOL_CACHE_TTL", "900"))
DEFAULT_TOOL_TIMEOUT_SEC = int(os.getenv("X3P_TOOL_TIMEOUT_SEC", "8"))
MAX_RETRIES = int(os.getenv("X3P_TOOL_MAX_RETRIES", "1"))
DOMAIN_REGEX = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
HTML_TAG_RE = re.compile(r"<[^>]+>")
SITEMAP_LOC_RE = re.compile(r"<loc>(.*?)</loc>", re.IGNORECASE)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)

TIME_RANGE_MAP = {
    "past_24_hours": "day",
    "past_24h": "day",
    "past_day": "day",
    "day": "day",
    "past_week": "week",
    "week": "week",
    "past_month": "month",
    "month": "month",
    "past_year": "year",
    "year": "year",
}


def _tool_cache(tool: Any) -> Dict[str, Any]:
    cache = getattr(tool, "_cache", None)
    if cache is None:
        cache = {}
        setattr(tool, "_cache", cache)
    return cache


def _cache_get(tool: Any, key: str) -> Optional[Dict[str, Any]]:
    entry = _tool_cache(tool).get(key)
    if not entry:
        return None
    if time.time() - entry["ts"] > CACHE_TTL:
        _tool_cache(tool).pop(key, None)
        return None
    return entry["value"]


def _cache_put(tool: Any, key: str, value: Dict[str, Any]) -> None:
    _tool_cache(tool)[key] = {"ts": time.time(), "value": value}


def _success(message: str, data: List[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": "ok", "message": message, "data": data}
    payload.update(extra)
    return payload


def _error(message: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": "error", "message": message, "data": []}
    payload.update(extra)
    return payload


def log_error(service: str, error: str) -> None:
    os.makedirs("runs", exist_ok=True)
    with open("runs/errors.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} - {service} - {error}\n")


def _request_with_retry(
    method: str,
    url: str,
    *,
    timeout_sec: int = DEFAULT_TOOL_TIMEOUT_SEC,
    max_retries: int = MAX_RETRIES,
    **kwargs: Any,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return requests.request(method, url, timeout=timeout_sec, **kwargs)
        except requests.Timeout as exc:
            last_error = exc
        except requests.RequestException as exc:
            last_error = exc
        if attempt < max_retries:
            time.sleep(0.2 + random.random() * 0.25)
    if last_error is not None:
        raise last_error
    raise RuntimeError("request failed without exception")


def sanitize_tavily_args(
    include_domains: Optional[Union[List[str], str]],
    exclude_domains: Optional[Union[List[str], str]],
    time_range: Optional[str],
    search_depth: Optional[str],
    max_results: int | str | None,
) -> dict:
    def _coerce_domains(v: Optional[Union[List[str], str]]) -> List[str]:
        if isinstance(v, str):
            s = v.strip()
            if not s or s.lower() == "none":
                return []
            return [d.strip() for d in s.split(",") if d.strip()]
        if v is None:
            return []
        return [d for d in v if isinstance(d, str) and d.strip()]

    inc = [d for d in _coerce_domains(include_domains) if DOMAIN_REGEX.match(d)]
    exc = [d for d in _coerce_domains(exclude_domains) if DOMAIN_REGEX.match(d)]

    mapped_time = None
    if isinstance(time_range, str) and time_range.strip():
        raw = time_range.strip().lower().replace("-", "_").replace(" ", "_")
        raw = raw.replace("last_", "past_")
        mapped_time = TIME_RANGE_MAP.get(raw)

    normalized_depth = "advanced"
    if isinstance(search_depth, str):
        sd = search_depth.strip().lower()
        if sd in {"basic", "advanced"}:
            normalized_depth = sd

    try:
        safe_max = max(1, min(int(max_results or 1), 25))
    except Exception:
        safe_max = 5

    return {
        "include_domains": inc,
        "exclude_domains": exc,
        "mapped_time_range": mapped_time,
        "normalized_search_depth": normalized_depth,
        "safe_max": safe_max,
    }


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _clean_html_text(html: str, max_chars: int = 5000) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _extract_title(html: str) -> str:
    m = TITLE_RE.search(html or "")
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:300]


class TavilyTool(BaseTool):
    name: str = "tavily_tool"
    description: str = "Search the web via Tavily and return {title,url,snippet}."
    env_vars: List[EnvVar] = [
        EnvVar(name="TAVILY_API_KEY", description="Tavily API key", required=True),
    ]

    def _run(
        self,
        query: str,
        max_results: int = 5,
        include_domains: Optional[Union[List[str], str]] = None,
        exclude_domains: Optional[Union[List[str], str]] = None,
        time_range: Optional[str] = None,
        search_depth: Optional[str] = "advanced",
    ) -> Dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return _error("Tavily query is required")

        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return _error("TAVILY_API_KEY is not set")

        san = sanitize_tavily_args(include_domains, exclude_domains, time_range, search_depth, max_results)
        payload: Dict[str, Any] = {
            "query": q,
            "num_results": san["safe_max"],
            "search_depth": san["normalized_search_depth"],
        }
        if san["include_domains"]:
            payload["include_domains"] = san["include_domains"]
        if san["exclude_domains"]:
            payload["exclude_domains"] = san["exclude_domains"]
        if san["mapped_time_range"]:
            payload["time_range"] = san["mapped_time_range"]

        cache_key = json.dumps(payload, sort_keys=True)
        cached = _cache_get(self, cache_key)
        if cached:
            return cached

        try:
            resp = _request_with_retry(
                "POST",
                "https://api.tavily.com/search",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
            resp.raise_for_status()
            rows = []
            for item in (resp.json() or {}).get("results", []):
                rows.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("snippet", ""),
                        "published_at": item.get("published_date") or item.get("published_at", ""),
                        "domain": _domain_from_url(item.get("url", "")),
                    }
                )
            result = _success(f"Retrieved {len(rows)} Tavily results for '{q}'.", rows)
            _cache_put(self, cache_key, result)
            return result
        except Exception as exc:
            log_error("Tavily", str(exc))
            return _error(f"Tavily search failed: {exc}")


class SocialTrendsTool(BaseTool):
    name: str = "social_trends_tool"
    description: str = "Collect social trend cues from Reddit and web trend headlines."

    def _run(
        self,
        include_platforms: Optional[Union[List[str], str]] = None,
        limit: int = 8,
        region: str = "united-states",
    ) -> Dict[str, Any]:
        if isinstance(include_platforms, str):
            include_platforms = [p.strip() for p in include_platforms.split(",") if p.strip()]

        platforms = {p.lower() for p in (include_platforms or ["reddit", "web"])}
        safe_limit = max(1, min(int(limit), 20))
        cache_key = json.dumps({"platforms": sorted(platforms), "limit": safe_limit, "region": region}, sort_keys=True)
        cached = _cache_get(self, cache_key)
        if cached:
            return cached

        items: List[Dict[str, Any]] = []

        if "reddit" in platforms:
            try:
                resp = _request_with_retry(
                    "GET",
                    f"https://www.reddit.com/r/popular.json?limit={safe_limit}",
                    headers={"User-Agent": USER_AGENT},
                )
                resp.raise_for_status()
                for child in (resp.json() or {}).get("data", {}).get("children", []):
                    data = child.get("data") or {}
                    items.append(
                        {
                            "platform": "reddit",
                            "title": data.get("title", ""),
                            "url": f"https://www.reddit.com{data.get('permalink', '')}",
                            "engagement": data.get("score"),
                            "published_at": datetime.fromtimestamp(
                                float(data.get("created_utc", 0) or 0), tz=timezone.utc
                            ).isoformat()
                            if data.get("created_utc")
                            else "",
                        }
                    )
            except Exception as exc:
                log_error("SocialTrends_Reddit", str(exc))

        if "web" in platforms:
            tavily_result = tavily_tool.run(
                query=f"trending workforce and care economy topics in {region}",
                max_results=safe_limit,
                time_range="past_week",
                search_depth="basic",
            )
            if str(tavily_result.get("status", "")).lower() == "ok":
                for row in tavily_result.get("data", []):
                    items.append(
                        {
                            "platform": "web",
                            "title": row.get("title", ""),
                            "url": row.get("url", ""),
                            "snippet": row.get("snippet", ""),
                            "published_at": row.get("published_at", ""),
                            "domain": row.get("domain", _domain_from_url(row.get("url", ""))),
                        }
                    )

        deduped: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (str(item.get("platform", "")).lower(), str(item.get("url", "")).strip())
            if not key[1] or key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        if not deduped:
            return _error("No trend items were verified from live sources.")

        result = _success(f"Collected {len(deduped[:safe_limit])} trend items from live sources.", deduped[:safe_limit])
        _cache_put(self, cache_key, result)
        return result


class X3PSiteSnapshotTool(BaseTool):
    name: str = "x3p_site_snapshot_tool"
    description: str = "Fetch and summarize key x3p.ai pages and sitemap-discovered pages."

    class X3PSiteSnapshotSchema(BaseModel):
        urls: Optional[Union[List[str], str]] = None
        include_sitemap: bool = True
        max_pages: int = 6

    args_schema = X3PSiteSnapshotSchema

    def _run(
        self,
        urls: Optional[Union[List[str], str]] = None,
        include_sitemap: bool = True,
        max_pages: int = 6,
    ) -> Dict[str, Any]:
        safe_pages = max(1, min(int(max_pages), 20))
        if isinstance(urls, str):
            seed_urls = [u.strip() for u in urls.split(",") if u.strip()]
        elif isinstance(urls, list):
            seed_urls = [str(u).strip() for u in urls if str(u).strip()]
        else:
            seed_urls = ["https://x3p.ai", "https://x3p.ai/about", "https://x3p.ai/contact"]

        discovered: List[str] = []
        if include_sitemap:
            try:
                sitemap_resp = _request_with_retry(
                    "GET",
                    "https://x3p.ai/sitemap.xml",
                    headers={"User-Agent": USER_AGENT},
                )
                if sitemap_resp.status_code == 200:
                    discovered.extend(SITEMAP_LOC_RE.findall(sitemap_resp.text))
            except Exception as exc:
                log_error("X3PSnapshot_Sitemap", str(exc))

        urls_final: List[str] = []
        for url in [*seed_urls, *discovered]:
            normalized = str(url).strip()
            if not normalized.startswith("https://x3p.ai"):
                continue
            if normalized not in urls_final:
                urls_final.append(normalized)
            if len(urls_final) >= safe_pages:
                break

        pages: List[Dict[str, Any]] = []
        for url in urls_final:
            try:
                resp = _request_with_retry(
                    "GET",
                    url,
                    headers={"User-Agent": USER_AGENT},
                )
                status = resp.status_code
                html = resp.text or ""
                page = {
                    "url": url,
                    "http_status": status,
                    "title": _extract_title(html),
                    "text": _clean_html_text(html, max_chars=8000),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                pages.append(page)
            except Exception as exc:
                log_error("X3PSnapshot_Page", f"{url}: {exc}")

        if not pages:
            return _error("Unable to fetch x3p.ai pages for snapshot.")
        return _success(
            f"Fetched {len(pages)} x3p.ai pages.",
            pages,
            metadata={"source_count": len(pages)},
        )


class TrendVerifierTool(BaseTool):
    name: str = "trend_verifier_tool"
    description: str = "Verify trend claims with fresh multi-source evidence and reject weak claims."

    class TrendVerifierToolSchema(BaseModel):
        query: str
        region: str = "united-states"
        recency_days: int = 7
        min_sources: int = 2
        max_results: int = 8

    args_schema = TrendVerifierToolSchema

    def _run(
        self,
        query: str,
        region: str = "united-states",
        recency_days: int = 7,
        min_sources: int = 2,
        max_results: int = 8,
    ) -> Dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return _error("Trend query is required.")

        safe_min_sources = max(2, min(int(min_sources), 5))
        safe_max_results = max(2, min(int(max_results), 20))
        if recency_days <= 1:
            time_range = "past_day"
        elif recency_days <= 7:
            time_range = "past_week"
        elif recency_days <= 31:
            time_range = "past_month"
        else:
            time_range = "past_year"

        tavily_result = tavily_tool.run(
            query=f"{q} {region} trend",
            max_results=safe_max_results,
            time_range=time_range,
            search_depth="advanced",
        )
        if str(tavily_result.get("status", "")).lower() != "ok":
            return _error(f"Trend verification failed: {tavily_result.get('message', 'Tavily unavailable')}")

        unique_by_domain: Dict[str, Dict[str, Any]] = {}
        for row in tavily_result.get("data", []):
            url = str(row.get("url", "")).strip()
            domain = row.get("domain") or _domain_from_url(url)
            if not url or not domain:
                continue
            if domain in unique_by_domain:
                continue
            unique_by_domain[domain] = {
                "title": row.get("title", ""),
                "url": url,
                "snippet": row.get("snippet", ""),
                "published_at": row.get("published_at", ""),
                "domain": domain,
            }
            if len(unique_by_domain) >= safe_max_results:
                break

        evidence = list(unique_by_domain.values())
        if len(evidence) < safe_min_sources:
            return _error(
                f"Insufficient verified sources for trend claim ({len(evidence)}/{safe_min_sources}).",
                metadata={
                    "query": q,
                    "region": region,
                    "source_count": len(evidence),
                    "required_sources": safe_min_sources,
                },
            )

        return _success(
            f"Verified trend evidence with {len(evidence)} independent sources.",
            evidence,
            metadata={
                "query": q,
                "region": region,
                "source_count": len(evidence),
                "required_sources": safe_min_sources,
                "recency_days": recency_days,
            },
        )


class BrandRetrieverTool(BaseTool):
    name: str = "brand_retriever_tool"
    description: str = "Retrieve relevant snippets from brand guide, brand snapshot, and recent outputs."

    def _run(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        try:
            q = (query or "").strip()
            if not q:
                return _error("Query is required")

            corpus: List[Tuple[str, str]] = []
            base = Path(__file__).resolve().parent
            guide_path = base / "config" / "default_brand_guide.yaml"
            if guide_path.exists():
                corpus.append((str(guide_path), guide_path.read_text(encoding="utf-8")))

            brand_brief = base.parent / "runs" / "brand_intel" / "brief_latest.json"
            if brand_brief.exists():
                try:
                    brief_data = json.loads(brand_brief.read_text(encoding="utf-8"))
                    corpus.append((str(brand_brief), json.dumps(brief_data, ensure_ascii=False)))
                except Exception:
                    pass

            outputs_dir = base.parent / "outputs"
            for sub in ("blog", "social", "brand"):
                p = outputs_dir / sub
                if not p.exists():
                    continue
                for file_path in sorted(p.glob("*.md"), reverse=True)[:2]:
                    try:
                        corpus.append((str(file_path), file_path.read_text(encoding="utf-8")))
                    except Exception:
                        continue

            tokens = set(re.findall(r"[a-zA-Z0-9]+", q.lower()))
            scored: List[Tuple[float, str, str]] = []
            for src, txt in corpus:
                for para in [x.strip() for x in re.split(r"\n\s*\n", txt) if x.strip()]:
                    p_tokens = re.findall(r"[a-zA-Z0-9]+", para.lower())
                    overlap = len(tokens.intersection(p_tokens))
                    if overlap:
                        scored.append((float(overlap), src, para[:900]))

            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[: max(1, min(top_k, 10))]
            if not top and corpus:
                return _success(
                    "No strong matches; returning brand guide excerpt",
                    [{"source": corpus[0][0], "snippet": corpus[0][1][:900]}],
                )
            return _success(
                f"Retrieved {len(top)} brand snippets for query",
                [{"source": src, "snippet": snippet} for _, src, snippet in top],
            )
        except Exception as exc:
            log_error("BrandRetriever", str(exc))
            return _error(str(exc))


tavily_tool = TavilyTool()
social_trends_tool = SocialTrendsTool()
x3p_site_snapshot_tool = X3PSiteSnapshotTool()
trend_verifier_tool = TrendVerifierTool()
brand_retriever_tool = BrandRetrieverTool()

__all__ = [
    "USER_AGENT",
    "sanitize_tavily_args",
    "tavily_tool",
    "social_trends_tool",
    "x3p_site_snapshot_tool",
    "trend_verifier_tool",
    "brand_retriever_tool",
]
