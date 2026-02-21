# Architecture

This document explains the system components, flows, and data produced by the X3P AI Marketing Studio.

## Components
- `app.py` — Streamlit UI and orchestrator. Phased execution, parallel lanes, run manifests, snapshots.
- `x3p_content_manager/crew.py` — Agents, tasks, crews. Defines mini‑crews and the full flow.
- `x3p_content_manager/config/agents.yaml` — Per‑agent LLM, tools, goals.
- `x3p_content_manager/config/tasks.yaml` — Task prompts, structure, and output requirements.
- `x3p_content_manager/tools.py` — External tools: Tavily, Semantic Scholar, PubMed, Social/YouTube, WorldBank/OECD, brand retriever.
- `x3p_content_manager/postprocess.py` — Sanitizers (blog format), inline citation markers.
- `x3p_content_manager/quality.py` — Quality checks and report (links, citations, structure).

## Execution modes
- Optimized — Evidence → SEO Early → Angle/Title Rerank → Blog → QA gate → Channels → QA+Compliance → Ops.
- Classic — Blog first → Channels + QA + Evidence in parallel → Ops.

Diagrams: `outputs/strategy/x3p_agent_graph.md` (Optimized + Classic, Mermaid).

## Data flow (Optimized)
1. Research/Scholar produce evidence → stored as text and passed via inputs.
2. SEO Early guidance → keywords/titles/meta prompts → saved for reuse.
3. Angle + Title Rerank propose options and preferred picks → passed to Writer.
4. Blog drafted → pre‑QA (Fact/Brand) → optional re‑edit if MAJOR/CRITICAL.
5. Channels (Social/Campaign/SEO/Design/Paid) run in parallel; QA/Compliance across assets.
6. Ops (Distribution, Calendar, Analytics, Client Report) consume outputs.

## Caching & Telemetry
- Topic fingerprint cache for Research/Scholar/SEO Early under `runs/fingerprint_cache.json`.
- Per‑stage usage includes `duration_ms` and a cache flag when reused.

## Artifacts
- Outputs: `outputs/<channel>/...`
- SEO meta: `outputs/seo/x3p_seo_meta_*.html`
- Packages: `outputs/all/x3p_package_*.zip`
- Manifest: `runs/manifest_*.json` (app_version, git, settings, usage, files)
- Snapshots: `runs/snapshots/<run_id>/` (agents, tasks, brand guide)

## Agents & Roles (high level)
- Strategy/Narrative: Strategist, Content Writer, Editor
- Channels: Social Manager, Campaign Designer, SEO Optimizer, Design Agent, Paid
- QA & Compliance: Fact Checker, Brand Guardian, Care Compliance Reviewer
- Evidence: Research Analyst, Scholar Agent
- Ops/Reporting: Performance Analyst, Creative Director

## Tools (selected)
- Tavily (web), Semantic Scholar, PubMed
- World Bank, OECD, RSS; YouTube search/trending/transcripts
- Brand retriever (embeddings or overlap)

See docs/DEVELOPMENT.md for extension patterns.
