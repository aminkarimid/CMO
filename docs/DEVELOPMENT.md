# Development

This document explains the structure and patterns for extending the studio.

## Project structure (selected)
- `app.py` — UI + orchestrator; phased pipeline (Optimized/Classic), manifests, snapshots
- `x3p_content_manager/crew.py` — agents, tasks, crews
- `x3p_content_manager/config/agents.yaml` — agent LLMs, tools, goals
- `x3p_content_manager/config/tasks.yaml` — prompts, structure, outputs
- `x3p_content_manager/tools.py` — external tools; add your tool here and reference in agents.yaml
- `x3p_content_manager/quality.py` — checks, link status, citation sanity, report
- `x3p_content_manager/postprocess.py` — blog sanitizers and citation markers

## Patterns

### Micro‑task rerank pattern (Title/Angle)
1) Add `*_rerank_task` in `tasks.yaml` with strict headings.
2) Add a crew in `crew.py` for the task (`*_rerank_crew`).
3) Call it in the Optimized pipeline (app.py) and parse the “Preferred” line.
4) Expose a Step‑3 expander UI to run manually and save results to `outputs/strategy/`.

### Adding an agent
- Define prompt, goals, and tools in `agents.yaml`.
- Reference the agent in `crew.py` and attach the right tasks.
- Keep temperatures low for QA/Compliance; higher for creative roles.

### Adding a tool
- Implement a `BaseTool` in `tools.py` with timeouts and minimal dependencies.
- Export it via `__all__` and add to agents in `agents.yaml`.
- For network tools, add retries/backoff and a graceful fallback path.

### Adding a task
- Define the `description`, `expected_output`, and `agent` in `tasks.yaml`.
- Use strict headings/bullets so validators can enforce correctness.
- Point the crew at the task and add to the appropriate phase.

## Testing & QA
- Use the UI’s Run Summary and Narrative QA panels to iterate quickly.
- `python -m x3p_content_manager.main lint` validates agents/tasks wiring and tool references.
- The Quality Report writes to `outputs/analytics/x3p_quality_report.md`.

## Manifests & Snapshots
- Every run writes a manifest (`runs/manifest_*.json`) with app version, git commit, settings, usage, and files.
- Config snapshots (agents/tasks/brand guide) land in `runs/snapshots/<run_id>/` for reproducibility.

## Style
- Keep tasks/agents minimal and declarative in YAML.
- Prefer small micro‑tasks to long monolithic prompts.
- Use strict schemas and post‑processing for reliability.
