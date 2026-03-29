"""Autonomous topic generation — decides what to write about next."""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from typing import Any, Optional

from x3p_content_manager.memory import get_recent_topics

logger = logging.getLogger(__name__)

# Fallback pillar topics when agent output is unparseable
_PILLAR_TOPICS = [
    "How X3P Creates Good Jobs in the Care Economy",
    "Why Home Care Workforce Stability Matters for Families",
    "Building Career Pathways for Immigrant Caregivers",
    "The Future of Home Care: Technology Meets Compassion",
    "How Employers Can Reduce Caregiver Turnover with X3P",
    "Understanding the Home Care Talent Shortage and Solutions",
    "X3P's Approach to Fair Wages and Predictable Schedules",
    "Childcare and Elder Care: Bridging the Access Gap",
    "What Makes a Good Job in Home Care Services",
    "How X3P Helps Families Find Trusted Caregivers",
]


@dataclass
class TopicSuggestion:
    """A generated topic suggestion for the content pipeline."""

    topic: str = ""
    audience: str = "families seeking care and caregivers seeking good jobs"
    tone: str = "evidence-based and empathetic"
    angle: str = ""
    rationale: str = ""
    source: str = "agent"  # "agent" or "fallback"


def _parse_topic_output(text: str) -> Optional[TopicSuggestion]:
    """Try to parse structured JSON from the agent output."""
    text = (text or "").strip()
    # Try to find JSON in the output
    for start_char, end_char in [("{", "}"), ]:
        idx_start = text.find(start_char)
        idx_end = text.rfind(end_char)
        if idx_start != -1 and idx_end > idx_start:
            candidate = text[idx_start : idx_end + 1]
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and data.get("topic"):
                    return TopicSuggestion(
                        topic=str(data.get("topic", "")).strip(),
                        audience=str(data.get("audience", "")).strip() or "families and caregivers",
                        tone=str(data.get("tone", "")).strip() or "evidence-based and empathetic",
                        angle=str(data.get("angle", "")).strip(),
                        rationale=str(data.get("rationale", "")).strip(),
                        source="agent",
                    )
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def _fallback_topic(recent_topics: list[str]) -> TopicSuggestion:
    """Pick a pillar topic not recently covered."""
    recent_lower = {t.lower() for t in recent_topics}
    available = [t for t in _PILLAR_TOPICS if t.lower() not in recent_lower]
    if not available:
        available = _PILLAR_TOPICS
    topic = random.choice(available)
    return TopicSuggestion(
        topic=topic,
        audience="families seeking care and caregivers seeking good jobs",
        tone="evidence-based and empathetic",
        angle="",
        rationale="Selected from pillar topic rotation",
        source="fallback",
    )


def generate_next_topic(
    brand_snapshot: Any = None,
    trend_brief: Any = None,
    recent_topic_limit: int = 20,
) -> TopicSuggestion:
    """Generate the next content topic using the strategist agent.

    Falls back to pillar topic rotation if the agent fails.
    """
    recent_topics = get_recent_topics(limit=recent_topic_limit)

    try:
        from x3p_content_manager.crew import X3PCareContentCrew

        crew_instance = X3PCareContentCrew()
        topic_crew = crew_instance.topic_crew()

        inputs = {
            "recent_topics": json.dumps(recent_topics) if recent_topics else "[]",
            "brand_snapshot": json.dumps(brand_snapshot) if brand_snapshot else "{}",
            "trend_signals": json.dumps(trend_brief) if trend_brief else "{}",
        }

        result = topic_crew.kickoff(inputs=inputs)
        output_text = ""
        if hasattr(result, "output") and result.output:
            output_text = str(result.output)
        elif hasattr(result, "to_dict"):
            payload = result.to_dict()
            output_text = str(payload.get("output", ""))
        else:
            output_text = str(result)

        suggestion = _parse_topic_output(output_text)
        if suggestion:
            # Ensure we're not repeating a recent topic
            if suggestion.topic.lower() in {t.lower() for t in recent_topics}:
                logger.warning("Agent suggested a recently covered topic, falling back")
                return _fallback_topic(recent_topics)
            return suggestion
        else:
            logger.warning("Could not parse agent topic output, falling back")
            return _fallback_topic(recent_topics)

    except Exception as exc:
        logger.error("Topic generation agent failed: %s, using fallback", exc)
        return _fallback_topic(recent_topics)
