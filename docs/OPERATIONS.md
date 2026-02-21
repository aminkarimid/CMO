# Operations

How to run, configure, and troubleshoot the studio.

## Run the UI

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Environment

- `X3P_PIPELINE_MODE` — `Optimized` (default) or `Classic`
- `X3P_MAX_WORKERS` — override adaptive concurrency (default = half CPU, 2–4)
- `TAVILY_API_KEY` — web research (optional)
- `SEMANTIC_SCHOLAR_KEY` — scholarly (optional)
- `SLACK_WEBHOOK_URL` — notifications (optional)
- `X3P_EMBED_RETRIEVER` — `1` to enable brand embeddings retriever (optional)
- `X3P_EMBED_ONLY` — `1` to force embeddings only (no fallback)

## Sidebar toggles
- Pipeline mode, Variants
- Auto‑package ZIP, Slack notify, Auto‑run Quality Report
- Auto‑append UTM, Inline [citation] (Blog), Auto‑export Calendar .ics
- Packaging quality gate (score threshold)
- Force preferred title in YAML
- Brand retriever mode (Auto/Force/Disable)

## CLI

```bash
python -m x3p_content_manager.main blog|social|campaign|seo|factcheck|research|scholar|calendar|distribution|paid_ads|brainstorm|client_report
python -m x3p_content_manager.main lint
```

## Artifacts
- Outputs in `outputs/<channel>/`
- SEO meta in `outputs/seo/`
- Title/Angle options in `outputs/strategy/`
- ZIPs in `outputs/all/`
- Manifests in `runs/manifest_*.json`
- Snapshots in `runs/snapshots/<run_id>/`

## Troubleshooting
- Missing keys: the UI degrades gracefully; consider mock fallbacks for Research/Scholar.
- Long runs: lower `X3P_MAX_WORKERS`, disable embeddings retriever, or use Classic mode.
- Packaging gate blocks ZIP: See Run Summary → Quality score and Narrative QA panel to improve.
- PDF export requires either WeasyPrint or wkhtmltopdf (`pdfkit`).
