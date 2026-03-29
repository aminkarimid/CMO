from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from x3p_content_manager.app.backend_health import apply_runtime_backend
from x3p_content_manager.app.brand_intel import load_brand_snapshot, refresh_brand_snapshot
from x3p_content_manager.app.errors import normalize_generation_error
from x3p_content_manager.app.input_contract import (
    DEFAULT_KEY_FACTS_TEXT,
    PIPELINES,
    PIPELINE_CONTENT_TYPES,
    default_inputs,
)
from x3p_content_manager.app.pipeline import (
    is_runtime_configuration_error,
    run_pipeline_with_quality_gate,
)
from x3p_content_manager.app.progress import LiveProgress
from x3p_content_manager.app.runtime_health import run_preflight_checks
from x3p_content_manager.app.template_guard import build_template_safe_inputs, missing_template_vars
from x3p_content_manager.crew import X3PCareContentCrew
from x3p_content_manager.main import load_default_brand_guide
from x3p_content_manager.memory import load_memory, remember_run
from x3p_content_manager.quality import REPORT_PATH as QUALITY_REPORT_PATH
from x3p_content_manager.quality import run_quality_checks as run_full_quality_checks
from x3p_content_manager.seo_schema import save_seo_meta
from x3p_content_manager.supabase_publisher import SupabasePublisher
from x3p_content_manager.utils import log_telemetry

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
AGENTS_CONFIG_PATH = CONFIG_DIR / "agents.yaml"
TASKS_CONFIG_PATH = CONFIG_DIR / "tasks.yaml"

OUTPUT_SUBDIRS = ["blog", "social", "factcheck", "brand", "analytics", "strategy", "all", "seo"]


def ensure_dirs() -> None:
    Path("runs").mkdir(exist_ok=True)
    Path("outputs").mkdir(exist_ok=True)
    for sub in OUTPUT_SUBDIRS:
        Path("outputs", sub).mkdir(parents=True, exist_ok=True)


def get_runtime_crew(force_refresh: bool = False) -> X3PCareContentCrew:
    """Session-local crew instance that can be refreshed on runtime mismatch."""
    base = Path(__file__).resolve().parents[1]
    version_parts = []
    for rel in ("crew.py", "tools.py", "config/agents.yaml", "config/tasks.yaml"):
        path = base / rel
        try:
            version_parts.append(f"{rel}:{path.stat().st_mtime_ns}")
        except Exception:
            version_parts.append(f"{rel}:missing")
    version = "|".join(version_parts)
    needs_refresh = (
        force_refresh
        or st.session_state.get("_x3p_crew_instance") is None
        or st.session_state.get("_x3p_crew_version") != version
    )
    if needs_refresh:
        st.session_state["_x3p_crew_instance"] = X3PCareContentCrew()
        st.session_state["_x3p_crew_version"] = version
    return st.session_state["_x3p_crew_instance"]


def _split_blog_and_social(text: str, pipeline: str) -> tuple[str, str]:
    raw = text or ""
    if pipeline == "Blog":
        return raw, ""
    if pipeline == "Social":
        return "", raw

    blog_idx = raw.find("## Blog")
    social_idx = raw.find("## Social")
    if blog_idx == -1 and social_idx == -1:
        return raw, ""
    blog = ""
    social = ""
    if blog_idx != -1 and social_idx != -1:
        blog = raw[blog_idx + len("## Blog") : social_idx].strip()
        social = raw[social_idx + len("## Social") :].strip()
    elif blog_idx != -1:
        blog = raw[blog_idx + len("## Blog") :].strip()
    else:
        social = raw[social_idx + len("## Social") :].strip()
    return blog, social


def _split_social_channels(text: str) -> tuple[str, str]:
    if not (text or "").strip():
        return "", ""
    blocks = [b for b in (text or "").split("## ") if b.strip()]
    lf: list[str] = []
    ig: list[str] = []
    for block in blocks:
        section = "## " + block.strip()
        heading = block.splitlines()[0].strip().lower()
        if heading.startswith("instagram"):
            ig.append(section)
        elif heading.startswith("linkedin") or heading.startswith("facebook"):
            lf.append(section)
    return "\n\n".join(lf).strip(), "\n\n".join(ig).strip()


def save_json(payload: Any, subfolder: str) -> str:
    ensure_dirs()
    path = Path("runs") / f"{subfolder}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def save_markdown(text: str, subfolder: str, base_name: str) -> str:
    ensure_dirs()
    out = Path("outputs") / subfolder
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{base_name}.md"
    path.write_text(text, encoding="utf-8")
    ts_path = out / f"{base_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    ts_path.write_text(text, encoding="utf-8")
    return str(ts_path)


def log_error(msg: str) -> None:
    ensure_dirs()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("runs/errors.log", "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def snapshot_configs(run_id: str) -> str | None:
    snap = Path("runs") / "snapshots" / run_id
    try:
        snap.mkdir(parents=True, exist_ok=True)
        shutil.copy2(AGENTS_CONFIG_PATH, snap / "agents.yaml")
        shutil.copy2(TASKS_CONFIG_PATH, snap / "tasks.yaml")
        shutil.copy2(CONFIG_DIR / "default_brand_guide.yaml", snap / "default_brand_guide.yaml")
        return str(snap)
    except Exception:
        return None


def write_run_manifest(
    run_id: str,
    *,
    pipeline: str,
    inputs: dict,
    files: list[str],
    usage_bundle: dict | None,
    settings: dict | None = None,
    health_report: dict | None = None,
    brand_snapshot_meta: dict | None = None,
    trend_brief_meta: dict | None = None,
    stage_durations: dict | None = None,
    failure_reasons: list[str] | None = None,
) -> str | None:
    try:
        data = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "pipeline": pipeline,
            "topic": inputs.get("topic", ""),
            "audience": inputs.get("audience", ""),
            "tone": inputs.get("tone", ""),
            "preferred_title": inputs.get("preferred_title", ""),
            "angle_choice": inputs.get("angle_choice", ""),
            "files": files,
            "usage": usage_bundle or {},
            "settings": settings or {},
            "health_report": health_report or {},
            "brand_snapshot_meta": brand_snapshot_meta or {},
            "trend_brief_meta": trend_brief_meta or {},
            "stage_durations": stage_durations or {},
            "failure_reasons": failure_reasons or [],
        }
        path = Path("runs") / f"manifest_{run_id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    except Exception:
        return None


def run_qa_checks(text: str, pipeline: str, inputs: dict) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.append({"name": "Non-empty output", "ok": bool((text or "").strip()), "details": f"chars={len(text or '')}"})
    if pipeline in {"Run All", "Blog"}:
        rows.append({"name": "Blog CTA", "ok": "visit x3p.ai" in (text or "").lower(), "details": "Visit x3p.ai should be present"})
    if pipeline in {"Run All", "Social"}:
        rows.append({"name": "Social sections", "ok": "## linkedin post 1" in (text or "").lower(), "details": "Required social headings should be present"})

    brand = inputs.get("brand_guide") or load_default_brand_guide()
    banned = {str(w).lower() for w in (brand.get("banned_words") or []) if str(w).strip()}
    found = sorted([w for w in banned if w in (text or "").lower()])
    rows.append({"name": "Banned words", "ok": len(found) == 0, "details": ", ".join(found) if found else "None"})
    return rows


def _dedupe_messages(messages: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for msg in messages:
        clean = str(msg or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(clean)
    return ordered


def _resolve_initial_theme() -> str:
    theme = str(st.session_state.get("ui_theme", "")).strip().lower()
    return theme if theme in {"dark", "light"} else "dark"


def _theme_css(theme: str) -> str:
    dark_tokens = {
        "bg_0": "#070b14",
        "bg_1": "#0c1324",
        "bg_2": "#111a2f",
        "mesh_0": "rgba(45,212,191,0.16)",
        "mesh_1": "rgba(14,165,233,0.14)",
        "card": "rgba(14,21,39,0.78)",
        "card_border": "rgba(121,143,185,0.22)",
        "card_shadow": "rgba(2,8,23,0.45)",
        "text_0": "#e9f1ff",
        "text_1": "#a8b9d8",
        "text_2": "#7f94bc",
        "brand_0": "#2dd4bf",
        "brand_1": "#0ea5e9",
        "brand_soft": "rgba(45,212,191,0.16)",
        "input_bg": "rgba(10,17,32,0.85)",
        "input_border": "rgba(121,143,185,0.32)",
        "focus_ring": "rgba(45,212,191,0.45)",
        "ok": "#34d399",
        "warn": "#f59e0b",
        "danger": "#f87171",
    }
    light_tokens = {
        "bg_0": "#f2f7ff",
        "bg_1": "#ffffff",
        "bg_2": "#edf3ff",
        "mesh_0": "rgba(14,165,233,0.10)",
        "mesh_1": "rgba(45,212,191,0.12)",
        "card": "rgba(255,255,255,0.90)",
        "card_border": "rgba(151,174,209,0.32)",
        "card_shadow": "rgba(15,23,42,0.12)",
        "text_0": "#0d1b32",
        "text_1": "#425c78",
        "text_2": "#5f7694",
        "brand_0": "#0f766e",
        "brand_1": "#0284c7",
        "brand_soft": "rgba(15,118,110,0.12)",
        "input_bg": "rgba(255,255,255,0.92)",
        "input_border": "rgba(151,174,209,0.44)",
        "focus_ring": "rgba(14,165,233,0.32)",
        "ok": "#047857",
        "warn": "#b45309",
        "danger": "#dc2626",
    }
    tokens = dark_tokens if theme == "dark" else light_tokens
    return """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=Manrope:wght@400;500;600;700&display=swap');
  :root {{
    --bg-0: {bg_0};
    --bg-1: {bg_1};
    --bg-2: {bg_2};
    --mesh-0: {mesh_0};
    --mesh-1: {mesh_1};
    --card: {card};
    --card-border: {card_border};
    --card-shadow: {card_shadow};
    --text-0: {text_0};
    --text-1: {text_1};
    --text-2: {text_2};
    --brand-0: {brand_0};
    --brand-1: {brand_1};
    --brand-soft: {brand_soft};
    --input-bg: {input_bg};
    --input-border: {input_border};
    --focus-ring: {focus_ring};
    --ok: {ok};
    --warn: {warn};
    --danger: {danger};
  }}
  .stApp {{
    background:
      radial-gradient(880px 460px at 5% -10%, var(--mesh-0) 0%, rgba(0,0,0,0) 62%),
      radial-gradient(820px 500px at 100% -15%, var(--mesh-1) 0%, rgba(0,0,0,0) 65%),
      linear-gradient(160deg, var(--bg-0) 0%, var(--bg-1) 52%, var(--bg-2) 100%);
    color: var(--text-0);
  }}
  .block-container {{
    max-width: 1120px;
    padding-top: 0.8rem;
    padding-bottom: 2.2rem;
  }}
  html, body, .stApp, .block-container, p, .stMarkdown, .stText {{
    color: var(--text-0);
    font-family: 'Manrope', sans-serif !important;
  }}
  h1, h2, h3, h4 {{
    color: var(--text-0);
    font-family: 'Sora', 'Manrope', sans-serif !important;
    letter-spacing: -0.02em;
  }}
  .mini-header {{
    margin-bottom: 0.5rem;
  }}
  .mini-kicker {{
    margin: 0 0 0.2rem 0;
    color: var(--brand-0);
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .mini-header h1 {{
    margin: 0;
    font-size: 1.8rem;
    line-height: 1.12;
  }}
  .mini-header p {{
    margin: 0.25rem 0 0 0;
    color: var(--text-1);
  }}
  .mini-hero {{
    border: 1px solid var(--card-border);
    background: linear-gradient(160deg, var(--card), rgba(255,255,255,0.02));
    border-radius: 18px;
    padding: 1rem 1.1rem;
    margin-bottom: 0.8rem;
    box-shadow: 0 14px 36px var(--card-shadow);
    backdrop-filter: blur(8px);
    animation: fadeUp 0.46s cubic-bezier(0.22, 1, 0.36, 1);
  }}
  .mini-hero h2 {{
    margin: 0;
    font-size: 1.2rem;
    line-height: 1.25;
  }}
  .mini-hero p {{
    margin: 0.4rem 0 0 0;
    color: var(--text-1);
  }}
  .mini-steps {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.42rem;
    margin-top: 0.72rem;
  }}
  .mini-steps span {{
    background: var(--brand-soft);
    border: 1px solid var(--card-border);
    color: var(--text-0);
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 600;
    padding: 0.24rem 0.6rem;
  }}
  .mini-form {{
    border: 1px solid var(--card-border);
    background: linear-gradient(180deg, var(--card), rgba(255,255,255,0.01));
    border-radius: 16px;
    padding: 1rem;
    margin-bottom: 0.8rem;
    box-shadow: 0 12px 28px var(--card-shadow);
    backdrop-filter: blur(10px);
    animation: fadeUp 0.52s cubic-bezier(0.22, 1, 0.36, 1);
  }}
  .mini-form-title {{
    margin: 0 0 0.4rem 0;
    color: var(--text-1);
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }}
  .mini-health {{
    border: 1px solid var(--card-border);
    background: linear-gradient(180deg, var(--card), rgba(255,255,255,0.01));
    border-radius: 14px;
    padding: 0.78rem 0.92rem;
    margin: 0.2rem 0 0.8rem 0;
    box-shadow: 0 10px 24px var(--card-shadow);
  }}
  .mini-health-grid {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.5rem;
    margin-top: 0.45rem;
  }}
  .mini-health-item {{
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 0.45rem 0.52rem;
    background: rgba(255,255,255,0.01);
  }}
  .mini-health-item strong {{
    display: block;
    font-size: 0.76rem;
    color: var(--text-1);
    margin-bottom: 0.1rem;
  }}
  .mini-health-item span {{
    font-size: 0.86rem;
    color: var(--text-0);
    overflow-wrap: anywhere;
  }}
  .mini-cap-grid {{
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.66rem;
    margin-bottom: 0.7rem;
  }}
  .mini-card {{
    border: 1px solid var(--card-border);
    background: linear-gradient(165deg, var(--card), rgba(255,255,255,0.02));
    border-radius: 14px;
    padding: 0.92rem 0.96rem;
    box-shadow: 0 10px 24px var(--card-shadow);
    transition: transform 0.18s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    animation: fadeUp 0.56s cubic-bezier(0.22, 1, 0.36, 1);
  }}
  .mini-card h3 {{
    margin: 0 0 0.24rem 0;
    font-size: 1rem;
  }}
  .mini-card p {{
    margin: 0;
    color: var(--text-1);
    font-size: 0.9rem;
    line-height: 1.4;
  }}
  @media (hover: hover) and (pointer: fine) {{
    .mini-card:hover {{
      transform: translateY(-3px);
      box-shadow: 0 18px 32px var(--card-shadow);
      border-color: var(--focus-ring);
    }}
  }}
  .mini-results-title {{
    color: var(--text-1);
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin: 0.25rem 0 0.55rem 0;
  }}
  [data-testid="stTextArea"] textarea,
  [data-testid="stTextInput"] input,
  [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
  [data-testid="stNumberInput"] input {{
    border-radius: 12px !important;
    border: 1px solid var(--input-border) !important;
    background: var(--input-bg) !important;
    color: var(--text-0) !important;
  }}
  [data-testid="stTextArea"] textarea::placeholder,
  [data-testid="stTextInput"] input::placeholder {{
    color: var(--text-2) !important;
    opacity: 1 !important;
  }}
  input:focus-visible,
  textarea:focus-visible,
  [data-baseweb="select"] *:focus-visible,
  button:focus-visible {{
    outline: 2px solid var(--focus-ring) !important;
    outline-offset: 1px !important;
  }}
  .stButton > button {{
    border-radius: 12px !important;
    border: 1px solid var(--brand-0) !important;
    background: linear-gradient(140deg, var(--brand-0), var(--brand-1)) !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    transition: transform 0.12s ease, filter 0.2s ease;
  }}
  .stButton > button:hover {{
    filter: brightness(1.04);
  }}
  .stButton > button:active {{
    transform: scale(0.99);
  }}
  [data-testid="stExpander"] details {{
    border: 1px solid var(--card-border) !important;
    background: var(--card) !important;
    border-radius: 12px !important;
  }}
  [data-testid="stExpander"] summary,
  [data-testid="stExpander"] label {{
    color: var(--text-0) !important;
  }}
  .stTabs [data-baseweb="tab-list"] {{
    gap: 0.45rem;
    flex-wrap: wrap;
  }}
  .stTabs [data-baseweb="tab"] {{
    border-radius: 999px;
    border: 1px solid var(--card-border);
    background: var(--brand-soft);
    color: var(--text-1);
    padding: 0.34rem 0.7rem;
  }}
  .stTabs [aria-selected="true"] {{
    border-color: var(--focus-ring) !important;
    background: linear-gradient(140deg, var(--brand-0), var(--brand-1)) !important;
    color: #ffffff !important;
  }}
  [data-testid="stAlert"] {{
    border-radius: 12px;
    border: 1px solid var(--card-border);
    background: var(--card);
    color: var(--text-0);
  }}
  .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown code {{
    color: var(--text-0);
    overflow-wrap: anywhere;
  }}
  .stCaption {{
    color: var(--text-1) !important;
  }}
  @keyframes fadeUp {{
    from {{
      opacity: 0;
      transform: translateY(6px);
    }}
    to {{
      opacity: 1;
      transform: translateY(0);
    }}
  }}
  @media (max-width: 1100px) {{
    .block-container {{
      max-width: 980px;
      padding-left: 1rem;
      padding-right: 1rem;
    }}
    .mini-hero, .mini-form {{
      padding: 0.92rem;
    }}
  }}
  @media (max-width: 900px) {{
    .block-container {{
      padding-left: 0.8rem;
      padding-right: 0.8rem;
    }}
    .mini-header h1 {{
      font-size: 1.5rem;
    }}
    .mini-cap-grid {{
      grid-template-columns: 1fr;
    }}
    .mini-health-grid {{
      grid-template-columns: 1fr 1fr;
    }}
    [data-testid="stHorizontalBlock"] {{
      flex-direction: column;
    }}
    [data-testid="stHorizontalBlock"] > div {{
      width: 100% !important;
      min-width: 0 !important;
    }}
    [data-testid="stRadio"] div[role="radiogroup"] {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.3rem;
    }}
  }}
  @media (max-width: 640px) {{
    .block-container {{
      padding-left: 0.65rem;
      padding-right: 0.65rem;
    }}
    .mini-header h1 {{
      font-size: 1.28rem;
    }}
    .mini-hero h2 {{
      font-size: 1.02rem;
    }}
    .mini-steps {{
      gap: 0.3rem;
    }}
    .mini-steps span {{
      padding: 0.2rem 0.48rem;
    }}
    .mini-form {{
      padding: 0.78rem;
    }}
    .mini-health-grid {{
      grid-template-columns: 1fr;
    }}
    .stButton > button {{
      min-height: 46px;
    }}
    .stTabs [data-baseweb="tab"] {{
      padding: 0.32rem 0.58rem;
    }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
      animation: none !important;
      transition: none !important;
      scroll-behavior: auto !important;
    }}
  }}
</style>
""".format(**tokens)


def _render_css(theme: str) -> None:
    st.markdown(_theme_css(theme), unsafe_allow_html=True)


def render_minimal_customer_ui() -> None:
    if "last_payload" not in st.session_state:
        st.session_state.last_payload = None
    if "last_text" not in st.session_state:
        st.session_state.last_text = None
    if "last_files" not in st.session_state:
        st.session_state.last_files = []
    if "last_inputs" not in st.session_state:
        st.session_state.last_inputs = default_inputs()
    if "last_pipeline" not in st.session_state:
        st.session_state["last_pipeline"] = "Run All"
    if "mini_show_quality" not in st.session_state:
        st.session_state["mini_show_quality"] = False
    if "_x3p_crew_instance" not in st.session_state:
        st.session_state["_x3p_crew_instance"] = None
    if "_x3p_crew_version" not in st.session_state:
        st.session_state["_x3p_crew_version"] = ""
    if "ui_theme" not in st.session_state:
        st.session_state["ui_theme"] = _resolve_initial_theme()
    if "ui_theme_toggle" not in st.session_state:
        st.session_state["ui_theme_toggle"] = "Dark" if st.session_state["ui_theme"] == "dark" else "Light"
    if "health_report_cache" not in st.session_state:
        try:
            st.session_state["health_report_cache"] = run_preflight_checks().to_dict()
        except Exception as exc:
            st.session_state["health_report_cache"] = {
                "ok": False,
                "message": f"Health check failed: {type(exc).__name__}",
                "checks": [],
                "backend": {"ok": False, "provider": "openai", "message": str(exc), "details": {}},
            }
    if "brand_snapshot_cache" not in st.session_state:
        st.session_state["brand_snapshot_cache"] = load_brand_snapshot().to_dict()

    _render_css(st.session_state["ui_theme"])

    recent = load_memory(limit=1)
    defaults = default_inputs()
    default_topic = (recent[0].get("topic") if recent else None) or defaults["topic"]
    default_audience = (recent[0].get("audience") if recent else None) or defaults["audience"]
    default_tone = (recent[0].get("tone") if recent else None) or defaults["tone"]

    header_left, header_right = st.columns([5, 1])
    with header_left:
        st.markdown(
            """
            <div class="mini-header">
              <p class="mini-kicker">CMO</p>
              <h1>Automated Marketing Studio</h1>
              <p>Dark-first workspace for blog and social content generation.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with header_right:
        st.markdown("<p class='mini-form-title'>Theme</p>", unsafe_allow_html=True)
        theme_choice = st.radio(
            "Theme",
            options=["Dark", "Light"],
            horizontal=True,
            key="ui_theme_toggle",
            label_visibility="collapsed",
        )

    selected_theme = str(theme_choice).strip().lower()
    if selected_theme != st.session_state.get("ui_theme"):
        st.session_state["ui_theme"] = selected_theme
        st.rerun()

    st.markdown(
        """
        <div class="mini-hero">
          <h2>Create one complete marketing package with built-in quality checks.</h2>
          <p>Generate blog, LinkedIn/Facebook, and Instagram assets with one focused wizard.</p>
          <div class="mini-steps"><span>Draft</span><span>Check</span><span>Adapt</span><span>Export</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    health_controls_left, health_controls_right = st.columns([5, 1])
    with health_controls_right:
        if st.button("Refresh health", key="mini_refresh_health", use_container_width=True):
            try:
                st.session_state["health_report_cache"] = run_preflight_checks().to_dict()
            except Exception as exc:
                st.session_state["health_report_cache"] = {
                    "ok": False,
                    "message": f"Health refresh failed: {type(exc).__name__}",
                    "checks": [],
                    "backend": {"ok": False, "provider": "openai", "message": str(exc), "details": {}},
                }
    with health_controls_left:
        health_data = st.session_state.get("health_report_cache", {}) or {}
        backend_data = health_data.get("backend", {}) if isinstance(health_data, dict) else {}
        checks = health_data.get("checks", []) if isinstance(health_data, dict) else []
        tool_ok = sum(1 for check in checks if check.get("ok")) if isinstance(checks, list) else 0
        tool_total = len(checks) if isinstance(checks, list) else 0
        brand_cache = st.session_state.get("brand_snapshot_cache", {}) or {}
        brand_age = float(brand_cache.get("age_hours") or 0.0)
        brand_sources = int(brand_cache.get("source_count") or 0)
        brand_label = "Not ready" if brand_age > 5000 else f"{brand_age:.1f}h old"
        health_state = "Healthy" if health_data.get("ok") else "Needs attention"
        st.markdown(
            f"""
            <div class="mini-health">
              <p class="mini-form-title">System health</p>
              <div class="mini-health-grid">
                <div class="mini-health-item"><strong>Status</strong><span>{health_state}</span></div>
                <div class="mini-health-item"><strong>LLM</strong><span>{backend_data.get("provider", "openai")} · {"OK" if backend_data.get("ok") else "Fail"}</span></div>
                <div class="mini-health-item"><strong>Tools</strong><span>{tool_ok}/{tool_total} checks passed</span></div>
                <div class="mini-health-item"><strong>x3p.ai Context</strong><span>{brand_label} · {brand_sources} sources</span></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if health_data.get("message"):
            st.caption(str(health_data.get("message")))

    pipeline_labels = {
        "Complete package": "Run All",
        "Blog only": "Blog",
        "Social only": "Social",
    }
    reverse_labels = {v: k for k, v in pipeline_labels.items()}
    runtime_estimates = {
        "Run All": "~2-5 min",
        "Blog": "~1-3 min",
        "Social": "~1-2 min",
    }

    st.markdown("<div class='mini-form'><p class='mini-form-title'>Launch</p>", unsafe_allow_html=True)
    selected_internal = st.session_state.get("selected_pipeline", "Run All")
    if selected_internal not in reverse_labels:
        selected_internal = "Run All"
    selected_label = st.radio(
        "Output mode",
        options=list(pipeline_labels.keys()),
        index=list(pipeline_labels.keys()).index(reverse_labels[selected_internal]),
        horizontal=True,
        key="mini_pipeline_label",
    )
    pipeline = pipeline_labels[selected_label]
    st.session_state["selected_pipeline"] = pipeline
    st.caption(f"Estimated runtime: {runtime_estimates.get(pipeline, '~2-5 min')}")

    tone_options = [
        "professional yet human-centered",
        "evidence-based and clear",
        "warm and inspiring",
        "concise and executive",
    ]
    tone_default = default_tone if default_tone in tone_options else tone_options[0]

    topic = st.text_area("Topic", value=default_topic, height=120, key="mini_topic")
    audience = st.text_input("Audience", value=default_audience, key="mini_audience")
    tone = st.selectbox("Tone", tone_options, index=tone_options.index(tone_default), key="mini_tone")

    key_facts_text = DEFAULT_KEY_FACTS_TEXT
    variants = 1
    show_full_quality = bool(st.session_state.get("mini_show_quality", False))
    preferred_title = st.session_state.get("preferred_title", "")
    angle_choice = st.session_state.get("angle_choice", "")
    trend_window_days = int(st.session_state.get("mini_trend_window_days", defaults.get("trend_window_days", 7)))
    manual_brand_refresh = False

    with st.expander("Advanced options", expanded=False):
        key_facts_text = st.text_area("Key facts (one per line)", value=DEFAULT_KEY_FACTS_TEXT, height=120, key="mini_key_facts")
        if pipeline in {"Run All", "Social"}:
            variants = st.slider("Social variants", 1, 3, 1, key="mini_variants")
            trend_window_days = st.slider("Trend recency window (days)", 1, 30, trend_window_days, key="mini_trend_window_days")
        show_full_quality = st.checkbox("Show full quality report", value=show_full_quality, key="mini_show_quality")
        preferred_title = st.text_input("Preferred title (optional)", value=preferred_title, key="mini_preferred_title")
        angle_choice = st.text_input("Angle (optional)", value=angle_choice, key="mini_angle_choice")
        manual_brand_refresh = st.button("Refresh x3p.ai context now", key="mini_refresh_brand_context")
        brand_cache = st.session_state.get("brand_snapshot_cache", {}) or {}
        brand_age = float(brand_cache.get("age_hours") or 0.0)
        age_label = "Not ready" if brand_age > 5000 else f"{brand_age:.1f}h"
        st.caption(
            f"Current context snapshot age: {age_label} "
            f"({int(brand_cache.get('source_count') or 0)} sources)"
        )

    run_btn = st.button("Generate content", type="primary", use_container_width=True, key="mini_run")
    st.markdown("</div>", unsafe_allow_html=True)

    if manual_brand_refresh:
        try:
            refreshed = refresh_brand_snapshot(force=True, max_age_hours=24)
            st.session_state["brand_snapshot_cache"] = refreshed.to_dict()
            st.success("x3p.ai brand context refreshed.")
        except Exception as exc:
            st.warning(f"Unable to refresh x3p.ai context: {exc}")

    st.markdown(
        """
        <div class="mini-cap-grid">
          <article class="mini-card">
            <h3>Blog</h3>
            <p>Long-form article structure with clear narrative and CTA flow.</p>
          </article>
          <article class="mini-card">
            <h3>LinkedIn + Facebook</h3>
            <p>Executive and community post formats tuned for conversion and trust.</p>
          </article>
          <article class="mini-card">
            <h3>Instagram</h3>
            <p>Short captions with visual direction and platform-friendly tone.</p>
          </article>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if run_btn:
        try:
            health_report = run_preflight_checks()
            health_report_dict = health_report.to_dict()
            st.session_state["health_report_cache"] = health_report_dict
        except Exception as exc:
            st.error(f"System preflight failed: {type(exc).__name__}")
            st.caption("Technical details were logged to runs/errors.log.")
            log_error(f"HealthReportError: {type(exc).__name__}: {exc}")
            return

        if not health_report.ok:
            st.error(health_report.message)
            failed_checks = [c for c in health_report.checks if c.critical and not c.ok]
            for check in failed_checks:
                st.caption(f"- {check.name}: {check.message}")
            st.caption("Generation did not start. Resolve critical health checks and retry.")
        else:
            runtime_backend_warning = apply_runtime_backend(health_report.backend)
            try:
                with st.spinner("Generating content..."):
                    start_ts = datetime.now()
                    recovered_events: list[str] = []
                    if runtime_backend_warning:
                        recovered_events.append(runtime_backend_warning)

                    brand_snapshot = refresh_brand_snapshot(force=False, max_age_hours=24)
                    st.session_state["brand_snapshot_cache"] = brand_snapshot.to_dict()
                    for warning in brand_snapshot.warnings:
                        recovered_events.append(warning)

                    inputs = default_inputs()
                    inputs["topic"] = (topic or inputs["topic"]).strip()
                    inputs["audience"] = (audience or inputs["audience"]).strip()
                    inputs["tone"] = (tone or inputs["tone"]).strip()
                    inputs["content_type"] = PIPELINE_CONTENT_TYPES.get(pipeline, inputs["content_type"])
                    inputs["key_facts"] = [line.strip() for line in (key_facts_text or "").splitlines() if line.strip()]
                    inputs["preferred_title"] = (preferred_title or "").strip()
                    inputs["angle_choice"] = (angle_choice or "").strip()
                    inputs["trend_window_days"] = int(trend_window_days)
                    inputs["brand_snapshot"] = json.dumps(brand_snapshot.brief, ensure_ascii=False)

                    st.session_state["preferred_title"] = inputs["preferred_title"]
                    st.session_state["angle_choice"] = inputs["angle_choice"]

                    missing_keys = missing_template_vars(inputs)
                    if missing_keys:
                        recovered_events.append("Recovered missing input keys automatically.")
                    inputs = build_template_safe_inputs(inputs)

                    ensure_dirs()
                    crew = get_runtime_crew(force_refresh=False)
                    _, subfolder, base_name = PIPELINES[pipeline]

                    live = LiveProgress("Run Progress")
                    try:
                        text, payload, usage, pipeline_warnings = run_pipeline_with_quality_gate(
                            crew,
                            pipeline,
                            inputs,
                            variants,
                            live,
                        )
                    except Exception as run_exc:
                        if is_runtime_configuration_error(run_exc):
                            crew = get_runtime_crew(force_refresh=True)
                            recovered_events.append("Recovered runtime crew configuration and retried automatically.")
                            text, payload, usage, pipeline_warnings = run_pipeline_with_quality_gate(
                                crew,
                                pipeline,
                                inputs,
                                variants,
                                live,
                            )
                        elif isinstance(run_exc, KeyError):
                            crew = get_runtime_crew(force_refresh=True)
                            recovered_events.append("Recovered cached crew/tool mismatch and retried automatically.")
                            text, payload, usage, pipeline_warnings = run_pipeline_with_quality_gate(
                                crew,
                                pipeline,
                                inputs,
                                variants,
                                live,
                            )
                        else:
                            raise

                    if not (isinstance(text, str) and text.strip()):
                        raise RuntimeError("Pipeline returned empty output.")

                    json_path = save_json(payload, subfolder)
                    md_path = save_markdown(text, subfolder, base_name)

                    meta_path = None
                    try:
                        blog_md = None
                        if pipeline == "Blog":
                            blog_md = text
                        elif pipeline == "Run All":
                            blog_md, _ = _split_blog_and_social(text, pipeline)
                        if blog_md:
                            meta_path = save_seo_meta(blog_md)
                    except Exception:
                        meta_path = None

                    files_now = [p for p in [json_path, md_path, meta_path] if p]
                    st.session_state.last_text = text
                    st.session_state.last_payload = payload
                    st.session_state.last_usage = usage
                    st.session_state.last_files = files_now
                    st.session_state.last_inputs = inputs
                    st.session_state["last_pipeline"] = pipeline

                    if show_full_quality:
                        try:
                            run_full_quality_checks(pipeline)
                            if QUALITY_REPORT_PATH.exists():
                                st.session_state.last_files.append(str(QUALITY_REPORT_PATH))
                        except Exception as exc:
                            pipeline_warnings.append(f"Full quality report failed: {exc}")

                    trend_payload = {}
                    if isinstance(payload, dict):
                        candidate = payload.get("Trend Intel")
                        if isinstance(candidate, dict):
                            trend_payload = candidate
                    kept_claims = trend_payload.get("kept_claims", []) if isinstance(trend_payload, dict) else []
                    dropped_claims = trend_payload.get("dropped_claims", []) if isinstance(trend_payload, dict) else []
                    trend_brief_meta = {
                        "claim_count": len(kept_claims) + len(dropped_claims),
                        "verified_count": len(kept_claims),
                        "dropped_count": len(dropped_claims),
                    }
                    brand_snapshot_meta = {
                        "captured_at": brand_snapshot.captured_at,
                        "age_hours": round(float(brand_snapshot.age_hours), 2),
                        "source_count": int(brand_snapshot.source_count),
                    }
                    stage_durations = {
                        stage: details.get("duration_ms")
                        for stage, details in (usage or {}).items()
                        if isinstance(details, dict) and "duration_ms" in details
                    }

                    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                    settings = {
                        "ui_mode": "minimal_v2",
                        "pipeline": pipeline,
                        "variants": int(variants),
                        "recovered_errors": sorted(set(recovered_events)),
                        "backend_status": {
                            "ok": health_report.backend.ok,
                            "provider": health_report.backend.provider,
                            "message": health_report.backend.message,
                            "details": health_report.backend.details,
                        },
                    }
                    manifest_path = write_run_manifest(
                        run_id,
                        pipeline=pipeline,
                        inputs=inputs,
                        files=st.session_state.last_files,
                        usage_bundle=usage if isinstance(usage, dict) else {},
                        settings=settings,
                        health_report=health_report_dict,
                        brand_snapshot_meta=brand_snapshot_meta,
                        trend_brief_meta=trend_brief_meta,
                        stage_durations=stage_durations,
                        failure_reasons=[],
                    )
                    if manifest_path:
                        st.session_state.last_files.append(manifest_path)

                    snapshot_configs(run_id)
                    remember_run(pipeline, inputs, text)
                    log_telemetry(pipeline=pipeline, success=True, tokens=usage if isinstance(usage, dict) else {}, message="Run complete")

                    # --- Auto-publish to Supabase ---
                    publisher = SupabasePublisher()
                    publish_result = None
                    social_publish_result = None
                    if publisher.is_configured():
                        blog_md_for_publish = None
                        social_md_for_publish = None
                        if pipeline == "Blog":
                            blog_md_for_publish = text
                        elif pipeline == "Run All":
                            _pub_blog, _pub_social = _split_blog_and_social(text, pipeline)
                            blog_md_for_publish = _pub_blog
                            social_md_for_publish = _pub_social
                        elif pipeline == "Social":
                            social_md_for_publish = text

                        if blog_md_for_publish:
                            publish_result = publisher.publish_blog(blog_md_for_publish)
                            if publish_result.ok:
                                st.success(f"Published to X3P: {publish_result.slug}")
                            else:
                                pipeline_warnings.append(f"Supabase publish failed: {publish_result.error}")

                        if social_md_for_publish:
                            blog_id = publish_result.blog_id if publish_result and publish_result.ok else None
                            social_publish_result = publisher.publish_social(social_md_for_publish, blog_id)
                            if social_publish_result.ok and social_publish_result.social_ids:
                                st.success(f"Published {len(social_publish_result.social_ids)} social posts to X3P")
                            elif social_publish_result.error and social_publish_result.error != "No social posts parsed":
                                pipeline_warnings.append(f"Social publish failed: {social_publish_result.error}")

                    st.session_state["last_publish_result"] = publish_result
                    st.session_state["last_social_publish_result"] = social_publish_result

                    for warning in _dedupe_messages(recovered_events + pipeline_warnings):
                        st.warning(f"⚠️ {warning}")

                    duration = (datetime.now() - start_ts).total_seconds()
                    st.success(f"Generation complete in {duration:.1f}s.")
            except Exception as exc:
                log_error(f"{type(exc).__name__}: {exc}")
                log_telemetry(pipeline=pipeline, success=False, message=str(exc))
                failure_usage = usage if "usage" in locals() and isinstance(usage, dict) else {}
                failure_stage_durations = {
                    stage: details.get("duration_ms")
                    for stage, details in failure_usage.items()
                    if isinstance(details, dict) and "duration_ms" in details
                }
                write_run_manifest(
                    datetime.now().strftime("%Y%m%d_%H%M%S"),
                    pipeline=pipeline,
                    inputs=inputs if "inputs" in locals() and isinstance(inputs, dict) else default_inputs(),
                    files=[],
                    usage_bundle=failure_usage,
                    settings={"ui_mode": "minimal_v2", "pipeline": pipeline, "failed": True},
                    health_report=health_report_dict,
                    brand_snapshot_meta=st.session_state.get("brand_snapshot_cache", {}),
                    trend_brief_meta={},
                    stage_durations=failure_stage_durations,
                    failure_reasons=[f"{type(exc).__name__}: {exc}"],
                )
                st.error(normalize_generation_error(exc))
                st.caption("Technical details were logged to runs/errors.log.")

    # --- Scheduler Controls ---
    with st.expander("Scheduled / Autonomous Runs", expanded=False):
        from x3p_content_manager.scheduler import ContentScheduler

        sched_status = ContentScheduler.get_schedule_status()
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.markdown(f"**Schedule enabled:** {'Yes' if sched_status.get('enabled') else 'No'}")
            st.markdown(f"**Cron:** `{sched_status.get('cron') or 'not set'}`")
        with col_s2:
            st.markdown(f"**Last run:** {sched_status.get('last_run') or 'never'}")
            last_res = sched_status.get("last_result") or {}
            if last_res:
                st.markdown(f"**Last topic:** {last_res.get('topic', 'N/A')}")
                st.markdown(f"**Result:** {'OK' if last_res.get('ok') else 'Failed'}")

        cron_presets = {
            "Daily at 9am": "0 9 * * *",
            "Twice a week (Mon/Thu)": "0 9 * * 1,4",
            "Weekly (Monday)": "0 9 * * 1",
            "Custom": "",
        }
        preset = st.selectbox("Schedule preset", list(cron_presets.keys()), key="sched_preset")
        cron_value = cron_presets.get(preset, "")
        if preset == "Custom":
            cron_value = st.text_input("Cron expression (min hour dom month dow)", value=sched_status.get("cron", ""), key="sched_cron_input")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("Save schedule", key="sched_save"):
                if cron_value.strip():
                    try:
                        scheduler = ContentScheduler()
                        scheduler.schedule_recurring(cron_value.strip())
                        scheduler.stop()  # Don't keep the scheduler running in the UI process
                        st.success(f"Schedule saved: `{cron_value.strip()}`")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Invalid cron: {e}")
                else:
                    st.warning("Enter a cron expression first.")
        with col_b2:
            if st.button("Run autonomous now", key="sched_run_once"):
                with st.spinner("Running autonomous pipeline (topic gen + content + publish)..."):
                    try:
                        result = ContentScheduler().run_once()
                        if result.get("ok"):
                            st.success(f"Autonomous run complete! Topic: **{result.get('topic')}** | Published: {result.get('published_slug', 'N/A')}")
                        else:
                            st.error(f"Autonomous run failed: {result.get('error')}")
                    except Exception as e:
                        st.error(f"Run failed: {e}")

    if st.session_state.get("last_text"):
        last_pipeline = st.session_state.get("last_pipeline", "Run All")
        blog_text, social_text = _split_blog_and_social(st.session_state.last_text or "", last_pipeline)
        lf_text, ig_text = _split_social_channels(social_text)
        st.markdown("<div class='mini-results-title'>Outputs</div>", unsafe_allow_html=True)
        blog_tab, lf_tab, ig_tab, files_tab, qa_tab, pub_tab = st.tabs(["Blog", "LinkedIn/Facebook", "Instagram", "Downloads", "Quality", "Publishing"])

        with blog_tab:
            if (blog_text or "").strip():
                st.markdown(blog_text)
            else:
                st.caption("No blog output in this mode.")

        with lf_tab:
            if (lf_text or "").strip():
                st.markdown(lf_text)
            elif (social_text or "").strip():
                st.markdown(social_text)
            else:
                st.caption("No LinkedIn/Facebook output in this mode.")

        with ig_tab:
            if (ig_text or "").strip():
                st.markdown(ig_text)
            elif last_pipeline == "Social" and (social_text or "").strip():
                st.markdown(social_text)
            else:
                st.caption("No Instagram output in this mode.")

        with files_tab:
            files = st.session_state.get("last_files", [])
            if not files:
                st.caption("No files generated yet.")
            for idx, fp in enumerate(files):
                if not fp or not os.path.exists(fp):
                    continue
                ext = Path(fp).suffix.lower()
                mime = "application/octet-stream"
                if ext == ".md":
                    mime = "text/markdown"
                elif ext == ".json":
                    mime = "application/json"
                elif ext == ".html":
                    mime = "text/html"
                with open(fp, "rb") as f:
                    st.download_button(
                        label=f"Download {os.path.basename(fp)}",
                        data=f.read(),
                        file_name=os.path.basename(fp),
                        mime=mime,
                        key=f"mini_download_{idx}_{os.path.basename(fp)}",
                    )
            st.caption("Files are saved under `outputs/` and `runs/` in the current project.")

        with qa_tab:
            qa_inputs = st.session_state.get("last_inputs", default_inputs())
            qa_rows = run_qa_checks(st.session_state.last_text or "", last_pipeline, qa_inputs)
            failed = [r for r in qa_rows if not r["ok"]]
            if failed:
                st.warning("Quality checks found issues:")
                for row in failed:
                    st.write(f"- {row['name']}: {row['details']}")
            else:
                st.success("Quality checks passed.")

            if st.button("Run full quality report", key="mini_full_qa"):
                try:
                    run_full_quality_checks(last_pipeline)
                    if QUALITY_REPORT_PATH.exists():
                        st.success("Full quality report generated.")
                except Exception as e:
                    st.warning(f"Unable to run full quality report: {e}")

            if QUALITY_REPORT_PATH.exists() and show_full_quality:
                try:
                    st.markdown(QUALITY_REPORT_PATH.read_text(encoding="utf-8"))
                except Exception:
                    st.caption("Unable to load quality report.")

        with pub_tab:
            publisher = SupabasePublisher()
            if not publisher.is_configured():
                st.info("Supabase not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY to enable auto-publishing.")
            else:
                pub_result = st.session_state.get("last_publish_result")
                social_pub_result = st.session_state.get("last_social_publish_result")

                if pub_result and pub_result.ok:
                    st.success(f"Blog published: **{pub_result.slug}**")
                    st.markdown(f"[View on X3P](https://x3p.ai/blog/{pub_result.slug})")
                elif pub_result and not pub_result.ok:
                    st.error(f"Blog publish failed: {pub_result.error}")
                else:
                    st.caption("No blog published in this run.")

                if social_pub_result and social_pub_result.ok and social_pub_result.social_ids:
                    st.success(f"{len(social_pub_result.social_ids)} social posts published")
                elif social_pub_result and social_pub_result.error and social_pub_result.error != "No social posts parsed":
                    st.error(f"Social publish failed: {social_pub_result.error}")

                st.markdown("---")
                st.markdown("**Recent Published Posts**")
                recent = publisher.list_published(limit=10)
                if recent:
                    for post in recent:
                        st.write(f"- [{post.get('title', 'Untitled')}](https://x3p.ai/blog/{post.get('slug', '')}) — {post.get('date', '')}")
                else:
                    st.caption("No published posts found.")
