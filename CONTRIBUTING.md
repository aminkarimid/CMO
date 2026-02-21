# Contributing to X3P Marketing Team

Thanks for your interest in improving the X3P Marketing Team app. This guide explains how to propose changes, add agents/tools, and validate your work.

## Quick Start
- Clone and create a virtualenv.
- Install dependencies: `pip install -r requirements.txt`.
- Run the UI: `streamlit run app.py`.
- Or use the CLI: `python -m x3p_content_manager.main run`.

## Branching & PRs
- Create a feature branch from `main`.
- Keep changes focused and small; update docs when behavior changes.
- Include rationale in your PR description and link to any related issues.
- Confirm the UI loads and a sample run completes before requesting review.

## Code Style
- Follow existing patterns and naming in the codebase.
- Prefer small, composable helpers over large functions.
- Keep functions pure where possible; isolate I/O and UI code.
- Type hints are encouraged; avoid single-letter variable names.

## Tests & Validation
- Prefer fast, specific checks for the areas you change.
- If you add a YAML/front‑matter helper, include idempotency checks (e.g., don’t duplicate tags).
- If you add a tool, provide a graceful fallback when network keys are missing.

## Docs
- If you change user‑facing behavior, update:
  - `README.md` for high‑level,
  - `docs/PLATFORM_OVERVIEW.md` for features & UI,
  - `docs/ARCHITECTURE.md` for flows & data,
  - `docs/OPERATIONS.md` for running and environment,
  - `docs/DEVELOPMENT.md` for patterns and extension.

## Adding Agents, Tools, Tasks
- Agents: Define in `x3p_content_manager/config/agents.yaml`. Keep role goals crisp. Provide tools explicitly.
- Tools: Add to `x3p_content_manager/tools.py`. Handle missing env/API keys gracefully and document usage.
- Tasks: Define in `x3p_content_manager/config/tasks.yaml`. Keep inputs minimal; prefer structured outputs.

## Performance
- Reuse shared clients and caches (`@st.cache_resource`, file caches in `runs/`).
- Log durations in telemetry and avoid unnecessary network calls.
- Consider micro‑task rerank patterns (Title/Angle) for better quality per token.

## Safety
- Avoid executing untrusted shell commands. Sanitize file paths if you add file‑open helpers.
- Ensure network tools respect timeouts and domains.
- Keep compliance/brand checks in the QA stage gated and explainable.

## Releasing
- Bump `APP_VERSION` in `app.py` when behavior or UI changes materially.
- Summarize notable changes in the PR description and link to docs updates.

Thanks for helping make X3P better!

