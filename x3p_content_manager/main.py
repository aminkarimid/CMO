#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

from x3p_content_manager.crew import X3PCareContentCrew
from x3p_content_manager.postprocess import sanitize_outputs
from x3p_content_manager.utils import extract_token_usage, get_api_key_messages, log_telemetry, print_api_key_messages
from x3p_content_manager.memory import remember_run

_CREW_INSTANCE: X3PCareContentCrew | None = None


def get_cached_crew() -> X3PCareContentCrew:
    global _CREW_INSTANCE
    if _CREW_INSTANCE is None:
        _CREW_INSTANCE = X3PCareContentCrew()
    return _CREW_INSTANCE


def load_default_brand_guide() -> dict:
    path = Path(__file__).resolve().parent / "config" / "default_brand_guide.yaml"
    if not path.exists():
        return {"voice": [], "tone": [], "banned_words": []}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"voice": [], "tone": [], "banned_words": []}
    return {
        "voice": data.get("voice", []) or [],
        "tone": data.get("tone", []) or [],
        "banned_words": data.get("banned_words", []) or [],
    }


def default_inputs() -> dict:
    return {
        "topic": "How X3P expands access to good jobs",
        "current_year": str(datetime.now().year),
        "audience": "employers, workers, and partners",
        "tone": "evidence-based and clear",
        "content_type": "blog + linkedin + facebook + instagram",
        "key_facts": [
            "Good jobs combine living wages, predictable schedules, advancement pathways, and worker voice.",
            "Care access constraints reduce labor-force participation and economic mobility.",
        ],
        "brief": {
            "objective": "Expand qualified placements with national partners.",
            "audience": "Employer operators, agency leaders, and caregivers.",
            "offer": "X3P Good Jobs Pathway.",
            "channels": ["blog", "LinkedIn", "Facebook", "Instagram"],
        },
        "brand_guide": load_default_brand_guide(),
        "trusted_domains": ["oecd.org", "worldbank.org", "who.int", "hbr.org", "reuters.com"],
        "preferred_title": "",
        "angle_choice": "",
        "campaign_outputs": "",
        "paid_ads_copy": "",
        "analytics_summary": "",
        "distribution_plan": "",
        "design_brief": "",
        "blog_outline": "",
        "blog_post": "",
        "blog_summary": "",
        "seo_pre_suggestions": "",
        "social_outputs": "",
        "factcheck_report": "",
        "brand_report": "",
        "research_summary": "",
        "scholar_summary": "",
    }


def _stringify_result(result) -> str:
    if hasattr(result, "output") and result.output:
        return str(result.output)
    if hasattr(result, "to_dict"):
        try:
            payload = result.to_dict()
            if isinstance(payload, dict) and isinstance(payload.get("output"), str):
                return payload["output"]
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            pass
    return str(result)


def _save_result(result, mode: str) -> str:
    runs = Path("runs")
    runs.mkdir(exist_ok=True)
    path = runs / f"{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    if hasattr(result, "to_dict"):
        try:
            payload = result.to_dict() or {"output": _stringify_result(result)}
        except Exception:
            payload = {"output": _stringify_result(result)}
    else:
        payload = {"output": _stringify_result(result)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _execute_pipeline(builder_name: str, mode: str, label: str):
    crew = getattr(get_cached_crew(), builder_name)()
    inputs = default_inputs()
    try:
        result = crew.kickoff(inputs=inputs)
        sanitize_outputs(mode)
        _save_result(result, mode)
        remember_run(mode, inputs, _stringify_result(result))
        log_telemetry(pipeline=mode, success=True, tokens=extract_token_usage(result), message=f"{label} completed")
        return result
    except Exception as e:
        log_telemetry(pipeline=mode, success=False, message=str(e))
        raise


def run_blog():
    return _execute_pipeline("blog_crew", "blog", "blog pipeline")


def run_social():
    return _execute_pipeline("social_crew", "social", "social pipeline")


def run_all():
    return _execute_pipeline("full_crew", "all", "full pipeline")


def lint_configs() -> int:
    base = Path(__file__).resolve().parent
    agents = yaml.safe_load((base / "config" / "agents.yaml").read_text(encoding="utf-8")) or {}
    tasks = yaml.safe_load((base / "config" / "tasks.yaml").read_text(encoding="utf-8")) or {}

    tool_names = {
        "tavily_tool",
        "social_trends_tool",
        "trend_verifier_tool",
        "x3p_site_snapshot_tool",
        "brand_retriever_tool",
    }

    errors: list[str] = []
    warnings: list[str] = []

    for task_id, info in tasks.items():
        owner = (info or {}).get("agent")
        if owner not in agents:
            errors.append(f"Task '{task_id}' references unknown agent '{owner}'.")

    for agent_id, info in agents.items():
        for t in (info or {}).get("tools", []) or []:
            if t not in tool_names:
                warnings.append(f"Agent '{agent_id}' uses unknown tool '{t}'.")

    print(f"Agents: {len(agents)} | Tasks: {len(tasks)}")
    if errors:
        print("Errors:")
        for e in errors:
            print(f" - {e}")
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f" - {w}")

    if errors:
        return 1
    print("Config lint passed.")
    return 0


def run_schedule_start():
    from x3p_content_manager.scheduler import ContentScheduler
    ContentScheduler().start()


def run_schedule_once():
    from x3p_content_manager.scheduler import ContentScheduler
    result = ContentScheduler().run_once()
    print(json.dumps(result, indent=2, default=str))


def run_schedule_status():
    from x3p_content_manager.scheduler import ContentScheduler
    print(json.dumps(ContentScheduler.get_schedule_status(), indent=2, default=str))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m x3p_content_manager.main [blog|social|all|lint|schedule-start|schedule-run-once|schedule-status]")
        raise SystemExit(1)

    mode = sys.argv[1].lower().strip()
    print_api_key_messages(get_api_key_messages())
    if mode == "lint":
        raise SystemExit(lint_configs())

    routes = {
        "blog": run_blog,
        "social": run_social,
        "all": run_all,
        "schedule-start": run_schedule_start,
        "schedule-run-once": run_schedule_once,
        "schedule-status": run_schedule_status,
    }
    if mode not in routes:
        print(f"Unknown mode: {mode}")
        raise SystemExit(1)

    routes[mode]()
