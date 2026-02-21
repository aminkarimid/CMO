# Platform Overview

X3P AI Marketing Studio is a multi‑agent system that turns a single topic brief into a complete, publish‑ready multi‑channel campaign: blog, social, campaign, paid ads, SEO, design prompts, and reporting — with evidence, brand guardrails, and care‑compliance baked in.

## Why it works
- Evidence‑first: Research + Scholar + SEO‑Early inform narrative; less rewriting, higher credibility.
- Parallel lanes: Channels, QA/Compliance, and Creative run concurrently where safe.
- Governance: severity‑based Fact‑check + Brand gate with one‑time re‑edit; Care Compliance pass flags PHI/claims.

## Pipelines
- Optimized (default): Research → Scholar → SEO Early → Angle + Title Rerank → Blog → Pre‑QA Gate → Channels → QA+Compliance → Ops
- Classic: Blog first → Channels + QA + Evidence (parallel) → Ops

Switch in the UI sidebar or via `X3P_PIPELINE_MODE`.

## Key features
- Title/Angle rerank micro‑tasks with manual override and re‑draft
- Inline citation markers and link checks; Quality Report
- SEO meta generator (OG/Twitter/JSON‑LD) written to `outputs/seo/`
- Packaging (ZIP), Slack notifications (optional)
- Manifests and config snapshots per run for reproducibility

## UI walkthrough
1) Content Studio → Quick actions (Run All, Blog, Social, …)
2) Step 1: Scout opportunities (optional topic suggestions)
3) Step 2: Choose focus per pipeline
4) Step 3: Generate & refine
   - Titles, Hooks & Angles panel (optional)
   - Generate content → Preview → Downloads → Run Summary → QA panels
   - Re‑draft Blog with chosen title from the preview expander

## Outputs
- Channel artifacts in `outputs/<channel>/`
- SEO meta HTML in `outputs/seo/`
- Title/Angle rerank notes in `outputs/strategy/`
- ZIP packages in `outputs/all/`
- Run manifests in `runs/manifest_*.json`
- Config snapshots in `runs/snapshots/<run_id>/`

See docs/OPERATIONS.md for runtime details and env configuration.
