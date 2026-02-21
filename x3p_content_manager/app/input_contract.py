from __future__ import annotations

from datetime import datetime
from typing import Any

from x3p_content_manager.main import load_default_brand_guide

SHARED_CONTEXT_KEYS = [
    "blog_outline",
    "blog_post",
    "blog_summary",
    "seo_pre_suggestions",
    "social_outputs",
    "factcheck_report",
    "brand_report",
    "research_summary",
    "scholar_summary",
]

DEFAULT_KEY_FACTS_TEXT = (
    "Good jobs combine living wages, predictable schedules, advancement pathways, and worker voice.\n"
    "Care access constraints reduce labor-force participation and economic mobility for many workers and families.\n"
    "Employers that invest in job quality can improve retention, productivity, and trust."
)

PIPELINE_CONTENT_TYPES = {
    "Blog": "blog article",
    "Social": "linkedin + facebook + instagram social posts",
    "Run All": "blog + linkedin + facebook + instagram",
}

PIPELINES = {
    "Blog": ("blog_crew", "blog", "x3p_blog_post"),
    "Social": ("social_crew", "social", "x3p_social_posts"),
    "Run All": ("full_crew", "all", "x3p_full_pipeline"),
}


def default_inputs() -> dict[str, Any]:
    base_inputs: dict[str, Any] = {
        "topic": "How platforms like X3P are solving the care crisis",
        "current_year": str(datetime.now().year),
        "audience": "general public",
        "tone": "professional yet human-centered",
        "content_type": "blog + linkedin + facebook + instagram",
        "key_facts": [
            "Good jobs combine living wages, predictable schedules, advancement pathways, and worker voice.",
            "Care access constraints reduce labor-force participation and economic mobility for many workers and families.",
            "Employers that invest in job quality can improve retention, productivity, and trust.",
        ],
        "brief": {
            "objective": "Secure qualified caregiver placements with health partners.",
            "audience": "Provider leaders, agency operators, and caregivers.",
            "offer": "X3P Good Jobs Pathway.",
            "channels": ["blog", "LinkedIn", "Facebook", "Instagram"],
        },
        "trusted_domains": [
            "mckinsey.com",
            "hbr.org",
            "reuters.com",
            "oecd.org",
            "who.int",
            "worldbank.org",
            "imf.org",
            "un.org",
        ],
        "brand_guide": load_default_brand_guide(),
        # Optional fields referenced by templates; always present to avoid crashes.
        "preferred_title": "",
        "angle_choice": "",
        "campaign_outputs": "",
        "paid_ads_copy": "",
        "analytics_summary": "",
        "distribution_plan": "",
        "design_brief": "",
    }
    for key in SHARED_CONTEXT_KEYS:
        base_inputs.setdefault(key, "")
    return base_inputs
