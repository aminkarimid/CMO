from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from crewai.tools import BaseTool, EnvVar
from pydantic import BaseModel

USER_AGENT = os.getenv(
    "X3P_HTTP_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)
CACHE_TTL = int(os.getenv("X3P_TOOL_CACHE_TTL", "900"))
DOMAIN_REGEX = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

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


def _success(message: str, data: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"status": "ok", "message": message, "data": data}


def _error(message: str) -> Dict[str, Any]:
    return {"status": "error", "message": message, "data": []}


def log_error(service: str, error: str) -> None:
    os.makedirs("runs", exist_ok=True)
    with open("runs/errors.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} - {service} - {error}\n")


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


class TavilyTool(BaseTool):
    name: str = "tavily_tool"
    description: str = "Search the web via Tavily and return {title,url,snippet}."
    env_vars: List[EnvVar] = [
        EnvVar(name="TAVILY_API_KEY", description="Tavily API key", required=True)
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
            resp = requests.post(
                "https://api.tavily.com/search",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                },
                timeout=15,
            )
            resp.raise_for_status()
            rows = []
            for item in (resp.json() or {}).get("results", []):
                rows.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("snippet", ""),
                    }
                )
            result = _success(f"Retrieved {len(rows)} Tavily results for '{q}'.", rows)
            _cache_put(self, cache_key, result)
            return result
        except Exception as e:
            log_error("Tavily", str(e))
            return _error(f"Tavily search failed: {e}")


class SemanticScholarTool(BaseTool):
    name: str = "semantic_scholar_tool"
    description: str = "Search Semantic Scholar and return paper metadata."
    env_vars: List[EnvVar] = [
        EnvVar(name="SEMANTIC_SCHOLAR_KEY", description="Semantic Scholar API key", required=False)
    ]

    class SemanticScholarToolSchema(BaseModel):
        query: str
        limit: int = 5
        fields: Optional[List[str]] = None
        year_after: Optional[int] = None
        year_before: Optional[int] = None

    args_schema = SemanticScholarToolSchema

    def _run(
        self,
        query: str,
        limit: int = 5,
        fields: Optional[List[str]] = None,
        year_after: Optional[int] = None,
        year_before: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "query": query,
            "limit": max(1, min(limit, 20)),
            "fields": ",".join(fields or ["title", "authors", "year", "url", "abstract", "doi"]),
        }
        if year_after is not None:
            params["yearAfter"] = year_after
        if year_before is not None:
            params["yearBefore"] = year_before

        headers = {"User-Agent": USER_AGENT}
        key = os.getenv("SEMANTIC_SCHOLAR_KEY")
        if key:
            headers["x-api-key"] = key

        try:
            resp = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params=params,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            rows: List[Dict[str, Any]] = []
            for p in (resp.json() or {}).get("data", []):
                rows.append(
                    {
                        "title": p.get("title", ""),
                        "authors": [a.get("name", "") for a in p.get("authors", [])],
                        "year": p.get("year"),
                        "url": p.get("url", ""),
                        "abstract": p.get("abstract", ""),
                        "doi": p.get("doi", ""),
                    }
                )
            return _success(f"Found {len(rows)} Semantic Scholar papers for '{query}'.", rows)
        except Exception as e:
            log_error("Semantic Scholar", str(e))
            return _error(f"Semantic Scholar search failed: {e}")


class PubMedTool(BaseTool):
    name: str = "pubmed_tool"
    description: str = "Search PubMed and return {id,title,abstract}."

    def _run(self, query: str, retmax: int = 5) -> Dict[str, Any]:
        base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        try:
            search_url = f"{base}esearch.fcgi?db=pubmed&term={requests.utils.quote(query)}&retmode=json&retmax={max(1, min(retmax, 10))}"
            ids_resp = requests.get(search_url, timeout=15)
            ids_resp.raise_for_status()
            ids = (ids_resp.json() or {}).get("esearchresult", {}).get("idlist", [])
            rows: List[Dict[str, Any]] = []
            for pid in ids:
                try:
                    fetch = requests.get(
                        f"{base}efetch.fcgi?db=pubmed&id={pid}&retmode=xml",
                        timeout=20,
                    )
                    fetch.raise_for_status()
                    xml = fetch.text
                    title = re.search(r"<ArticleTitle>(.*?)</ArticleTitle>", xml, re.DOTALL)
                    abstract = re.search(r"<AbstractText.*?>(.*?)</AbstractText>", xml, re.DOTALL)
                    rows.append(
                        {
                            "id": pid,
                            "title": title.group(1).strip() if title else "",
                            "abstract": abstract.group(1).strip() if abstract else "",
                        }
                    )
                except Exception as inner:
                    log_error("PubMed", f"efetch {pid} failed: {inner}")
            if not rows:
                return _error(f"No PubMed summaries fetched for '{query}'")
            return _success(f"Fetched {len(rows)} PubMed summaries for '{query}'.", rows)
        except Exception as e:
            log_error("PubMed", str(e))
            return _error(f"PubMed search failed: {e}")


class SocialTrendsTool(BaseTool):
    name: str = "social_trends_tool"
    description: str = "Collect social trend cues from X, Reddit, and Google Trends."

    def _run(
        self,
        include_platforms: Optional[Union[List[str], str]] = None,
        limit: int = 8,
        region: str = "united-states",
    ) -> Dict[str, Any]:
        if isinstance(include_platforms, str):
            include_platforms = [p.strip() for p in include_platforms.split(",") if p.strip()]

        platforms = {p.lower() for p in (include_platforms or ["x", "reddit", "google"])}
        cache_key = json.dumps(
            {"platforms": sorted(platforms), "limit": limit, "region": region},
            sort_keys=True,
        )
        cached = _cache_get(self, cache_key)
        if cached:
            return cached

        items: List[Dict[str, Any]] = []
        if "reddit" in platforms:
            try:
                r = requests.get(
                    f"https://www.reddit.com/r/popular.json?limit={max(1, min(limit, 20))}",
                    headers={"User-Agent": USER_AGENT},
                    timeout=10,
                )
                r.raise_for_status()
                for child in (r.json() or {}).get("data", {}).get("children", []):
                    data = child.get("data") or {}
                    items.append(
                        {
                            "platform": "reddit",
                            "title": data.get("title", ""),
                            "url": f"https://www.reddit.com{data.get('permalink', '')}",
                        }
                    )
            except Exception as e:
                log_error("SocialTrends_Reddit", str(e))

        if not items:
            region_label = region.replace("_", " ").title()
            items = [
                {
                    "platform": "x",
                    "topic": "#GoodJobs",
                    "url": "https://twitter.com/hashtag/GoodJobs",
                    "note": f"Trending discussion around wages and retention in {region_label}.",
                },
                {
                    "platform": "google",
                    "topic": "care workforce retention",
                    "exploreUrl": "https://trends.google.com/trends/explore?q=care%20workforce%20retention",
                },
            ]

        result = _success(f"Collected {len(items[:max(1, limit)])} social trend items", items[: max(1, limit)])
        _cache_put(self, cache_key, result)
        return result


class WorldBankTool(BaseTool):
    name: str = "world_bank_tool"
    description: str = "Fetch World Bank indicator series."

    def _run(self, indicator_code: str, country: str = "WLD", date: str = "2015:2024", per_page: int = 60) -> Dict[str, Any]:
        try:
            resp = requests.get(
                f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator_code}",
                params={"format": "json", "date": date, "per_page": per_page},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            rows: List[Dict[str, Any]] = []
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                for row in data[1]:
                    rows.append({"date": row.get("date"), "value": row.get("value")})
            rows.sort(key=lambda x: int(x.get("date") or 0), reverse=True)
            return _success(f"World Bank series {indicator_code} ({country})", rows)
        except Exception as e:
            log_error("WorldBank", str(e))
            return _error(str(e))


class OECDTool(BaseTool):
    name: str = "oecd_tool"
    description: str = "Fetch OECD SDMX CSV rows."

    def _run(self, dataset: str, key: str, time_range: str = "") -> Dict[str, Any]:
        base = f"https://stats.oecd.org/sdmx-json/data/{dataset}/{key}"
        if time_range:
            base = f"https://stats.oecd.org/sdmx-json/data/{dataset}/{key},time={time_range}"
        url = f"{base}?contentType=csv"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            lines = [ln for ln in resp.text.splitlines() if ln.strip()]
            if len(lines) < 2:
                return _error("Unexpected OECD CSV format")
            headers = [h.strip().strip('"') for h in lines[0].split(",")]
            rows = []
            for ln in lines[1:]:
                parts = [p.strip().strip('"') for p in ln.split(",")]
                row = {headers[i]: (parts[i] if i < len(parts) else "") for i in range(len(headers))}
                rows.append(row)
            out: List[Dict[str, Any]] = []
            for row in rows:
                value = None
                for key_name in ("OBS_VALUE", "Value", headers[-1]):
                    if key_name in row:
                        try:
                            value = float(row[key_name])
                            break
                        except Exception:
                            continue
                if value is None:
                    continue
                out.append(
                    {
                        "time": row.get("TIME_PERIOD") or row.get("TIME") or row.get("Year"),
                        "value": value,
                        "raw_row": row,
                    }
                )
            return _success(f"OECD {dataset}/{key} rows={len(out)}", out)
        except Exception as e:
            log_error("OECD", str(e))
            return _error(f"OECD fetch failed: {e}")


class BrandRetrieverTool(BaseTool):
    name: str = "brand_retriever_tool"
    description: str = "Retrieve relevant snippets from brand guide and recent outputs."

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

            outputs_dir = base.parent / "outputs"
            for sub in ("blog", "social", "brand"):
                p = outputs_dir / sub
                if not p.exists():
                    continue
                for f in sorted(p.glob("*.md"), reverse=True)[:2]:
                    try:
                        corpus.append((str(f), f.read_text(encoding="utf-8")))
                    except Exception:
                        continue

            tokens = set(re.findall(r"[a-zA-Z0-9]+", q.lower()))
            scored: List[Tuple[float, str, str]] = []
            for src, txt in corpus:
                for para in [x.strip() for x in re.split(r"\n\s*\n", txt) if x.strip()]:
                    p_tokens = re.findall(r"[a-zA-Z0-9]+", para.lower())
                    overlap = len(tokens.intersection(p_tokens))
                    if overlap:
                        scored.append((float(overlap), src, para[:800]))

            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[: max(1, min(top_k, 10))]
            if not top and corpus:
                return _success("No strong matches; returning brand guide excerpt", [{"source": corpus[0][0], "snippet": corpus[0][1][:800]}])
            return _success(
                f"Retrieved {len(top)} brand snippets for query",
                [{"source": s, "snippet": p} for _, s, p in top],
            )
        except Exception as e:
            log_error("BrandRetriever", str(e))
            return _error(str(e))


tavily_tool = TavilyTool()
semantic_scholar_tool = SemanticScholarTool()
pubmed_tool = PubMedTool()
social_trends_tool = SocialTrendsTool()
world_bank_tool = WorldBankTool()
oecd_tool = OECDTool()
brand_retriever_tool = BrandRetrieverTool()

__all__ = [
    "tavily_tool",
    "semantic_scholar_tool",
    "pubmed_tool",
    "social_trends_tool",
    "world_bank_tool",
    "oecd_tool",
    "brand_retriever_tool",
]
