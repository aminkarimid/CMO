from __future__ import annotations

import streamlit as st

from x3p_content_manager.app.backend_health import BackendStatus, apply_runtime_backend, preflight_backend
from x3p_content_manager.app.errors import normalize_generation_error
from x3p_content_manager.app.input_contract import (
    DEFAULT_KEY_FACTS_TEXT,
    PIPELINES,
    PIPELINE_CONTENT_TYPES,
    SHARED_CONTEXT_KEYS,
    default_inputs,
)
from x3p_content_manager.app.pipeline import (
    run_builder_instance,
    run_full_pipeline_parallel,
    run_pipeline_with_quality_gate,
)
from x3p_content_manager.app.template_guard import (
    build_template_safe_inputs,
    extract_missing_template_var as _extract_missing_template_var,
    extract_task_placeholders,
    missing_template_vars as _missing_template_vars,
)
from x3p_content_manager.app.ui_minimal import render_minimal_customer_ui

__all__ = [
    "BackendStatus",
    "DEFAULT_KEY_FACTS_TEXT",
    "PIPELINES",
    "PIPELINE_CONTENT_TYPES",
    "SHARED_CONTEXT_KEYS",
    "build_template_safe_inputs",
    "default_inputs",
    "extract_task_placeholders",
    "normalize_generation_error",
    "apply_runtime_backend",
    "preflight_backend",
    "run_builder_instance",
    "run_full_pipeline_parallel",
    "run_pipeline_with_quality_gate",
    "_extract_missing_template_var",
    "_missing_template_vars",
]


def main() -> None:
    st.set_page_config(page_title="X3P Automated Marketing Team", layout="wide")
    render_minimal_customer_ui()


if __name__ == "__main__":
    main()
