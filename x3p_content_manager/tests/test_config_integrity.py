from pathlib import Path

import yaml


def test_agents_and_tasks_are_core_scope_only():
    base = Path(__file__).resolve().parents[1] / "config"
    agents = yaml.safe_load((base / "agents.yaml").read_text(encoding="utf-8")) or {}
    tasks = yaml.safe_load((base / "tasks.yaml").read_text(encoding="utf-8")) or {}

    allowed_agents = {
        "strategist",
        "content_writer",
        "editor",
        "social_media_manager",
        "fact_checker",
        "brand_guardian",
    }
    allowed_tasks = {
        "strategy_outline_task",
        "writing_task",
        "editing_task",
        "social_media_task",
        "fact_check_task",
        "brandcheck_task",
    }

    assert set(agents.keys()) == allowed_agents
    assert set(tasks.keys()) == allowed_tasks

    for task_id, task in tasks.items():
        assert task.get("agent") in agents, f"{task_id} references unknown agent"
