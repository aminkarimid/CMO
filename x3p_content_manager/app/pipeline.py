from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

from x3p_content_manager.app.input_contract import PIPELINES
from x3p_content_manager.app.template_guard import extract_missing_template_var
from x3p_content_manager.app.trend_intel import build_verified_trend_brief
from x3p_content_manager.crew import X3PCareContentCrew
from x3p_content_manager.utils import extract_token_usage

LABEL_TO_CONTEXT_KEY = {
    "Blog": "blog_post",
    "Social": "social_outputs",
    "Fact-check": "factcheck_report",
    "Brand Check": "brand_report",
    "Trend Intel": "trend_brief",
}

LABEL_TO_AGENT = {
    "Blog": "Strategist + Writer + Editor",
    "Blog (Re-Edit)": "Editor",
    "Trend Intel": "Trend Intelligence Analyst",
    "Social": "Social Media Manager",
    "Fact-check": "Fact Checker",
    "Brand Check": "Brand Guardian",
}

BACKEND_ERROR_INDICATORS = (
    "apiconnectionerror",
    "ollamaexception",
    "openaiexception - connection error",
    "openaiexception",
    "authenticationerror",
    "invalid api key",
    "operation not permitted",
    "connection refused",
    "connection error.",
    "no usable backend found",
    "ollama is not reachable",
)
QUOTA_ERROR_INDICATORS = (
    "insufficient_quota",
    "quota exceeded",
    "exceeded your current quota",
    "billing details",
    "error code: 429",
    "ratelimiterror",
)
RUNTIME_CONFIG_ERROR_INDICATORS = (
    "validation error for crew",
    "input should be a valid boolean",
    "\nmemory\n",
)
TOOL_HEALTH_ERROR_INDICATORS = (
    "tavily_api_key",
    "trend verification failed",
    "no trend items were verified",
    "critical health checks failed",
    "tool unavailable",
    "x3p.ai probe failed",
)


class BackendUnavailableError(RuntimeError):
    """Raised when the configured LLM backend is unavailable."""


class RuntimeConfigurationError(RuntimeError):
    """Raised when app/crew runtime wiring is inconsistent and needs refresh."""


class StageTimeoutError(RuntimeError):
    """Raised when a pipeline stage exceeds timeout budget."""


class StageDependencyError(RuntimeError):
    """Raised when stage prerequisites or outputs are invalid."""


class ToolHealthError(RuntimeError):
    """Raised when critical tool checks fail at runtime."""


class QuotaExceededError(RuntimeError):
    """Raised when provider quota has been exceeded."""


def _step_timeout_seconds() -> int:
    env = str(os.getenv("X3P_STEP_TIMEOUT_SEC", "")).strip()
    if env.isdigit():
        return max(15, int(env))
    return 30


def _run_timeout_seconds() -> int:
    env = str(os.getenv("X3P_RUN_TIMEOUT_SEC", "")).strip()
    if env.isdigit():
        return max(60, int(env))
    return 180


def is_transient_runtime_error(exc: Exception | str) -> bool:
    msg = str(exc).lower()
    transient_hints = (
        "connection reset by peer",
        "connection aborted",
        "read timed out",
        "timed out",
        "timeout",
        "broken pipe",
    )
    return any(h in msg for h in transient_hints)


def is_backend_unavailable_error(exc: Exception | str) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in BACKEND_ERROR_INDICATORS)


def is_quota_error(exc: Exception | str) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in QUOTA_ERROR_INDICATORS)


def is_runtime_configuration_error(exc: Exception | str) -> bool:
    msg = str(exc).lower()
    if all(h in msg for h in RUNTIME_CONFIG_ERROR_INDICATORS):
        return True
    return "validation error for crew" in msg and "memory" in msg and "valid boolean" in msg


def is_tool_health_error(exc: Exception | str) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in TOOL_HEALTH_ERROR_INDICATORS)


def _log_error(msg: str) -> None:
    try:
        os.makedirs("runs", exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("runs/errors.log", "a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def build_mock_blog_content(topic: str, audience: str | None = None) -> str:
    audience_label = audience or "general audience"
    return (
        f"# {topic}\n\n"
        "### Opportunity Gap\n"
        f"The care economy continues to face workforce instability affecting {audience_label}.\n\n"
        "### How X3P Builds Good Jobs\n"
        "X3P helps connect workers to better opportunities with structured pathways and employer alignment.\n\n"
        "### Outcomes & Partnerships\n"
        "Use conservative, evidence-first language for any claims that need verification.\n\n"
        "**Call to Action**\n"
        "Visit x3p.ai or contact partnerships@x3p.ai.\n\n"
        "## Sources\n"
        "- [E001] X3P — [x3p.ai](https://x3p.ai)\n"
    )


def build_mock_social_content(topic: str, audience: str | None = None) -> str:
    aud = audience or "your audience"
    return (
        "## LinkedIn post 1\n"
        f"{topic} matters for {aud}. Visit x3p.ai\n"
        "Hashtags: #X3P #GoodJobs\n\n"
        "## LinkedIn post 2\n"
        "Use verified trend evidence and clear calls to action. Visit x3p.ai\n"
        "Hashtags: #CareEconomy #Workforce\n\n"
        "## Facebook post 1\n"
        "Communities do better when job quality improves. Visit x3p.ai\n"
        "Hashtags: #Community #GoodJobs\n\n"
        "## Facebook post 2\n"
        "Reliable workforce pathways improve trust and retention. Visit x3p.ai\n"
        "Hashtags: #Workforce #X3P\n\n"
        "## Instagram caption 1\n"
        "Suggested visual: Care team collaboration\nVisit x3p.ai\n"
        "Hashtags: #CareWork #GoodJobs\n\n"
        "## Instagram caption 2\n"
        "Suggested visual: Career pathway milestones\nVisit x3p.ai\n"
        "Hashtags: #CareerPathways #X3P"
    )


def _parse_json_header(text: str) -> dict | None:
    if not text:
        return None
    first = text.strip().splitlines()[0].strip()
    if first.startswith("{") and first.endswith("}"):
        try:
            return json.loads(first)
        except Exception:
            return None
    return None


def _severity_rank(value: str | None) -> int:
    order = {"none": 0, "minor": 1, "major": 2, "critical": 3}
    return order.get(str(value or "").strip().lower(), 0)


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\s-]", "", (value or "").strip().lower())
    value = re.sub(r"[\s_-]+", "-", value).strip("-")
    return value or "post"


def _force_title_in_yaml(md_text: str, title: str | None) -> str:
    if not md_text or not title:
        return md_text
    match = re.match(r"^---\s*\n(.*?)\n---", md_text, flags=re.DOTALL)
    if not match:
        return md_text
    fm = match.group(1)
    if re.search(r"(?m)^title:\s*", fm):
        fm = re.sub(r"(?m)^title:\s*.*$", f'title: "{title}"', fm)
    else:
        fm = f'title: "{title}"\n{fm}'

    slug = _slugify(title)
    if re.search(r"(?m)^slug:\s*", fm):
        fm = re.sub(r"(?m)^slug:\s*.*$", f"slug: {slug}", fm)
    else:
        fm = f"slug: {slug}\n{fm}"
    return md_text.replace(match.group(0), f"---\n{fm}\n---", 1)


def _inject_angle_in_yaml(md_text: str, angle: str | None) -> str:
    if not md_text or not angle:
        return md_text
    match = re.match(r"^---\s*\n(.*?)\n---", md_text, flags=re.DOTALL)
    if not match:
        return md_text
    fm = match.group(1)
    if "tags:" not in fm:
        fm = f"tags:\n  - {angle}\n{fm}"
    elif angle.lower() not in fm.lower():
        fm = re.sub(r"(?m)^tags:\s*$", f"tags:\n  - {angle}", fm)
    return md_text.replace(match.group(0), f"---\n{fm}\n---", 1)


def _to_serializable(result: Any) -> tuple[str, Any]:
    if hasattr(result, "output") and isinstance(result.output, str):
        payload = result.to_dict() if hasattr(result, "to_dict") else {"output": result.output}
        return result.output, payload
    if hasattr(result, "to_dict"):
        payload = result.to_dict()
        if isinstance(payload, dict):
            output = payload.get("output")
            if isinstance(output, str):
                return output, payload
        return json.dumps(payload, ensure_ascii=False), payload
    return str(result), {"text": str(result)}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert_run_budget(deadline: float, stage: str) -> None:
    if time.perf_counter() > deadline:
        raise StageTimeoutError(f"Run timeout reached before stage '{stage}'.")


def run_builder_instance(
    crew: X3PCareContentCrew,
    builder_name: str,
    label: str,
    base_inputs: dict,
    variant_count: int = 1,
) -> dict[str, Any]:
    local_inputs = copy.deepcopy(base_inputs)
    timeout_sec = _step_timeout_seconds()
    started_at = _utc_now_iso()
    start = time.perf_counter()
    recovery_notes: list[str] = []

    result: dict[str, Any] = {
        "label": label,
        "text": "",
        "payload": {},
        "usage": None,
        "mock": False,
        "warning": None,
    }

    def _invoke_with_timeout(kickoff_fn: Callable[[dict], Any], payload: dict) -> Any:
        result_holder: dict[str, Any] = {}
        error_holder: dict[str, BaseException] = {}
        completed = threading.Event()

        def _worker() -> None:
            try:
                result_holder["result"] = kickoff_fn(payload)
            except BaseException as exc:  # pragma: no cover
                error_holder["error"] = exc
            finally:
                completed.set()

        thread = threading.Thread(target=_worker, name=f"x3p-{label.lower()}-kickoff", daemon=True)
        thread.start()
        if not completed.wait(timeout=timeout_sec):
            raise TimeoutError(f"{label} exceeded {timeout_sec}s timeout")
        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("result")

    def _kickoff_with_recovery(kickoff_fn: Callable[[dict], Any], payload: dict) -> Any:
        try:
            return _invoke_with_timeout(kickoff_fn, payload)
        except Exception as exc:
            missing_key = extract_missing_template_var(str(exc))
            if missing_key:
                payload.setdefault(missing_key, "")
                recovery_notes.append(f"Recovered missing input key '{missing_key}' and retried automatically.")
                return _invoke_with_timeout(kickoff_fn, payload)
            raise

    try:
        if label == "Social" and variant_count > 1:
            texts: list[str] = []
            payload_map: dict[str, Any] = {}
            usage = None
            for idx in range(1, variant_count + 1):
                local_inputs["variant"] = idx
                crew_instance = getattr(crew, builder_name)()
                response = _kickoff_with_recovery(lambda data: crew_instance.kickoff(inputs=data), local_inputs)
                usage = usage or extract_token_usage(response)
                text, payload = _to_serializable(response)
                key = f"Variant {idx}"
                texts.append(f"### {key}\n\n{text}")
                payload_map[key] = payload
            result["text"] = "\n\n".join(texts)
            result["payload"] = payload_map
            result["usage"] = usage
        else:
            crew_instance = getattr(crew, builder_name)()
            response = _kickoff_with_recovery(lambda data: crew_instance.kickoff(inputs=data), local_inputs)
            result["usage"] = extract_token_usage(response) or {}
            text, payload = _to_serializable(response)
            result["text"] = text
            result["payload"] = payload
    except Exception as exc:
        if is_quota_error(exc):
            _log_error(f"{label} quota exceeded: {type(exc).__name__}: {exc}")
            raise QuotaExceededError(
                "OpenAI quota exceeded. Update billing or use a key with available quota, then retry."
            ) from exc
        if is_runtime_configuration_error(exc):
            _log_error(f"{label} runtime configuration error: {type(exc).__name__}: {exc}")
            raise RuntimeConfigurationError(f"{label} runtime configuration error: {exc}") from exc
        if is_backend_unavailable_error(exc):
            _log_error(f"{label} backend unavailable: {type(exc).__name__}: {exc}")
            raise BackendUnavailableError(f"{label} backend unavailable: {exc}") from exc
        if isinstance(exc, TimeoutError) or is_transient_runtime_error(exc):
            _log_error(f"{label} timeout/transient error: {type(exc).__name__}: {exc}")
            raise StageTimeoutError(f"{label} timed out after {timeout_sec}s.") from exc
        if is_tool_health_error(exc):
            _log_error(f"{label} tool health error: {type(exc).__name__}: {exc}")
            raise ToolHealthError(f"{label} failed due to tool health issue: {exc}") from exc
        _log_error(f"{label} stage dependency error: {type(exc).__name__}: {exc}")
        raise StageDependencyError(f"{label} failed: {exc}") from exc
    finally:
        local_inputs.pop("variant", None)

    duration_ms = int((time.perf_counter() - start) * 1000)
    usage = result.get("usage") or {}
    if isinstance(usage, dict):
        usage["duration_ms"] = duration_ms
        usage["started_at"] = started_at
        usage["finished_at"] = _utc_now_iso()
    else:
        usage = {"duration_ms": duration_ms, "started_at": started_at, "finished_at": _utc_now_iso()}
    result["usage"] = usage

    if recovery_notes:
        result["warning"] = " ".join(sorted(set(recovery_notes)))
    return result


def _run_trend_intel_stage(inputs: dict[str, Any]) -> dict[str, Any]:
    started_at = _utc_now_iso()
    start = time.perf_counter()
    brief = build_verified_trend_brief(
        topic=str(inputs.get("topic") or "X3P"),
        audience=str(inputs.get("audience") or "general audience"),
        tone=str(inputs.get("tone") or "professional"),
        trend_window_days=int(inputs.get("trend_window_days") or 7),
        min_sources=2,
        max_claims=4,
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    payload = brief.to_dict()
    result = {
        "label": "Trend Intel",
        "text": json.dumps(payload, ensure_ascii=False, indent=2),
        "payload": payload,
        "usage": {
            "duration_ms": duration_ms,
            "started_at": started_at,
            "finished_at": _utc_now_iso(),
        },
        "warning": None,
    }
    if not brief.ok:
        raise StageDependencyError(brief.message)
    return result


def _run_fact_brand_checks(
    crew: X3PCareContentCrew,
    inputs: dict,
    progress: Any | None,
    payload_bundle: dict[str, Any],
    usage_bundle: dict[str, Any],
    warnings: list[str],
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    builders = [("factcheck_crew", "Fact-check"), ("brandcheck_crew", "Brand Check")]
    results: dict[str, dict[str, Any]] = {}

    if progress:
        for _, label in builders:
            progress.start(label, LABEL_TO_AGENT.get(label, ""))

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_map = {
            executor.submit(run_builder_instance, crew, builder_name, label, inputs, 1): label
            for builder_name, label in builders
        }
        for future in as_completed(future_map):
            label = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                if progress:
                    progress.done(label, ok=False, note=str(exc), duration_ms=None)
                raise
            results[label] = result
            if progress:
                progress.done(
                    label,
                    ok=True,
                    note=result.get("warning") or "",
                    duration_ms=(result.get("usage") or {}).get("duration_ms"),
                )

    fact = results.get("Fact-check", {"label": "Fact-check", "text": "", "payload": {}, "usage": {}})
    brand = results.get("Brand Check", {"label": "Brand Check", "text": "", "payload": {}, "usage": {}})

    for result in (fact, brand):
        label = result.get("label", "")
        payload_bundle[label] = result.get("payload")
        usage_bundle[label] = result.get("usage")
        context_key = LABEL_TO_CONTEXT_KEY.get(label)
        if context_key:
            inputs[context_key] = result.get("text", "") or ""
        if result.get("warning"):
            warnings.append(result["warning"])

    fsev = _severity_rank((_parse_json_header(fact.get("text", "")) or {}).get("severity"))
    bsev = _severity_rank((_parse_json_header(brand.get("text", "")) or {}).get("severity"))
    return fact, brand, max(fsev, bsev) >= 2


def run_pipeline_with_quality_gate(
    crew: X3PCareContentCrew,
    pipeline: str,
    inputs: dict,
    variants: int,
    progress: Any | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any], list[str]]:
    if pipeline == "Run All":
        return run_full_pipeline_parallel(crew, inputs, variants, progress)

    payload_bundle: dict[str, Any] = {}
    usage_bundle: dict[str, Any] = {}
    warnings: list[str] = []
    deadline = time.perf_counter() + _run_timeout_seconds()

    def _store_result(result: dict[str, Any]) -> None:
        label = result.get("label", "")
        payload_bundle[label] = result.get("payload")
        usage_bundle[label] = result.get("usage")
        context_key = LABEL_TO_CONTEXT_KEY.get(label)
        if context_key:
            inputs[context_key] = result.get("text", "") or ""
        if result.get("warning"):
            warnings.append(result["warning"])

    if pipeline == "Blog":
        _assert_run_budget(deadline, "Blog")
        if progress:
            progress.start("Blog", LABEL_TO_AGENT.get("Blog", ""))
        try:
            blog_result = run_builder_instance(crew, "blog_crew", "Blog", inputs, 1)
        except Exception as exc:
            if progress:
                progress.done("Blog", ok=False, note=str(exc), duration_ms=None)
            raise
        if progress:
            progress.done("Blog", ok=True, note=blog_result.get("warning") or "", duration_ms=(blog_result.get("usage") or {}).get("duration_ms"))
        blog_text = _inject_angle_in_yaml(_force_title_in_yaml(blog_result.get("text", ""), inputs.get("preferred_title")), inputs.get("angle_choice"))
        blog_result["text"] = blog_text
        _store_result(blog_result)

        _assert_run_budget(deadline, "Fact/Brand")
        _, _, need_reedit = _run_fact_brand_checks(crew, inputs, progress, payload_bundle, usage_bundle, warnings)
        if need_reedit:
            _assert_run_budget(deadline, "Blog (Re-Edit)")
            if progress:
                progress.start("Blog (Re-Edit)", LABEL_TO_AGENT.get("Blog (Re-Edit)", ""))
            try:
                reedit = run_builder_instance(crew, "editor_crew", "Blog (Re-Edit)", inputs, 1)
            except Exception as exc:
                if progress:
                    progress.done("Blog (Re-Edit)", ok=False, note=str(exc), duration_ms=None)
                raise
            if progress:
                progress.done("Blog (Re-Edit)", ok=True, note=reedit.get("warning") or "", duration_ms=(reedit.get("usage") or {}).get("duration_ms"))
            new_blog = reedit.get("text", "")
            if isinstance(new_blog, str) and new_blog.strip():
                new_blog = _inject_angle_in_yaml(_force_title_in_yaml(new_blog, inputs.get("preferred_title")), inputs.get("angle_choice"))
                reedit["text"] = new_blog
                blog_text = new_blog
                inputs["blog_post"] = new_blog
            else:
                warnings.append("Blog re-edit returned empty output; kept initial blog draft.")
            _store_result(reedit)
            warnings.append("Quality gate triggered a one-time blog re-edit.")
        return blog_text, payload_bundle, usage_bundle, warnings

    if pipeline == "Social":
        _assert_run_budget(deadline, "Trend Intel")
        if progress:
            progress.start("Trend Intel", LABEL_TO_AGENT.get("Trend Intel", ""))
        try:
            trend_result = _run_trend_intel_stage(inputs)
        except Exception as exc:
            if progress:
                progress.done("Trend Intel", ok=False, note=str(exc), duration_ms=None)
            raise
        if progress:
            progress.done(
                "Trend Intel",
                ok=True,
                note=trend_result.get("warning") or "",
                duration_ms=(trend_result.get("usage") or {}).get("duration_ms"),
            )
        _store_result(trend_result)

        _assert_run_budget(deadline, "Social")
        if progress:
            progress.start("Social", LABEL_TO_AGENT.get("Social", ""))
        try:
            social_result = run_builder_instance(crew, "social_crew", "Social", inputs, variants)
        except Exception as exc:
            if progress:
                progress.done("Social", ok=False, note=str(exc), duration_ms=None)
            raise
        if progress:
            progress.done("Social", ok=True, note=social_result.get("warning") or "", duration_ms=(social_result.get("usage") or {}).get("duration_ms"))
        social_text = social_result.get("text", "")
        _store_result(social_result)

        _assert_run_budget(deadline, "Fact/Brand")
        _, _, need_rerun = _run_fact_brand_checks(crew, inputs, progress, payload_bundle, usage_bundle, warnings)
        if need_rerun:
            _assert_run_budget(deadline, "Social rerun")
            if progress:
                progress.start("Social", LABEL_TO_AGENT.get("Social", ""))
            try:
                rerun = run_builder_instance(crew, "social_crew", "Social", inputs, variants)
            except Exception as exc:
                if progress:
                    progress.done("Social", ok=False, note=str(exc), duration_ms=None)
                raise
            if progress:
                progress.done("Social", ok=True, note=rerun.get("warning") or "Re-run after QA findings", duration_ms=(rerun.get("usage") or {}).get("duration_ms"))
            rerun_text = rerun.get("text", "")
            if isinstance(rerun_text, str) and rerun_text.strip():
                social_text = rerun_text
            else:
                rerun["text"] = social_text
                warnings.append("Social re-run returned empty output; kept initial social draft.")
            _store_result(rerun)
            warnings.append("Quality gate triggered a one-time social re-run using fact-check and brand feedback.")
        return social_text, payload_bundle, usage_bundle, warnings

    crew_builder_name, _, _ = PIPELINES[pipeline]
    result = run_builder_instance(crew, crew_builder_name, pipeline, inputs, variants if pipeline == "Social" else 1)
    _store_result(result)
    return result.get("text", ""), payload_bundle, usage_bundle, warnings


def run_full_pipeline_parallel(
    crew: X3PCareContentCrew,
    inputs: dict,
    variants: int,
    progress: Any | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any], list[str]]:
    payload_bundle: dict[str, Any] = {}
    usage_bundle: dict[str, Any] = {}
    warnings: list[str] = []
    deadline = time.perf_counter() + _run_timeout_seconds()

    def _store(result: dict[str, Any]) -> None:
        label = result.get("label", "")
        payload_bundle[label] = result.get("payload")
        usage_bundle[label] = result.get("usage")
        context_key = LABEL_TO_CONTEXT_KEY.get(label)
        if context_key:
            inputs[context_key] = result.get("text", "") or ""
        if result.get("warning"):
            warnings.append(result["warning"])

    _assert_run_budget(deadline, "Blog")
    if progress:
        progress.start("Blog", LABEL_TO_AGENT.get("Blog", ""))
    try:
        blog_result = run_builder_instance(crew, "blog_crew", "Blog", inputs, 1)
    except Exception as exc:
        if progress:
            progress.done("Blog", ok=False, note=str(exc), duration_ms=None)
        raise
    if progress:
        progress.done("Blog", ok=True, note=blog_result.get("warning") or "", duration_ms=(blog_result.get("usage") or {}).get("duration_ms"))

    blog_text = _inject_angle_in_yaml(_force_title_in_yaml(blog_result.get("text", ""), inputs.get("preferred_title")), inputs.get("angle_choice"))
    blog_result["text"] = blog_text
    _store(blog_result)

    _assert_run_budget(deadline, "Fact/Brand")
    _, _, need_reedit = _run_fact_brand_checks(crew, inputs, progress, payload_bundle, usage_bundle, warnings)
    if need_reedit:
        _assert_run_budget(deadline, "Blog (Re-Edit)")
        if progress:
            progress.start("Blog (Re-Edit)", LABEL_TO_AGENT.get("Blog (Re-Edit)", ""))
        try:
            reedit = run_builder_instance(crew, "editor_crew", "Blog (Re-Edit)", inputs, 1)
        except Exception as exc:
            if progress:
                progress.done("Blog (Re-Edit)", ok=False, note=str(exc), duration_ms=None)
            raise
        if progress:
            progress.done("Blog (Re-Edit)", ok=True, note=reedit.get("warning") or "", duration_ms=(reedit.get("usage") or {}).get("duration_ms"))
        new_blog = reedit.get("text", "")
        if isinstance(new_blog, str) and new_blog.strip():
            new_blog = _inject_angle_in_yaml(_force_title_in_yaml(new_blog, inputs.get("preferred_title")), inputs.get("angle_choice"))
            reedit["text"] = new_blog
            blog_text = new_blog
            inputs["blog_post"] = new_blog
        else:
            warnings.append("Blog re-edit returned empty output; kept initial blog draft.")
        _store(reedit)
        warnings.append("Quality gate triggered a one-time blog re-edit before social generation.")

    _assert_run_budget(deadline, "Trend Intel")
    if progress:
        progress.start("Trend Intel", LABEL_TO_AGENT.get("Trend Intel", ""))
    try:
        trend_result = _run_trend_intel_stage(inputs)
    except Exception as exc:
        if progress:
            progress.done("Trend Intel", ok=False, note=str(exc), duration_ms=None)
        raise
    if progress:
        progress.done(
            "Trend Intel",
            ok=True,
            note=trend_result.get("warning") or "",
            duration_ms=(trend_result.get("usage") or {}).get("duration_ms"),
        )
    _store(trend_result)

    _assert_run_budget(deadline, "Social")
    if progress:
        progress.start("Social", LABEL_TO_AGENT.get("Social", ""))
    try:
        social_result = run_builder_instance(crew, "social_crew", "Social", inputs, variants)
    except Exception as exc:
        if progress:
            progress.done("Social", ok=False, note=str(exc), duration_ms=None)
        raise
    if progress:
        progress.done("Social", ok=True, note=social_result.get("warning") or "", duration_ms=(social_result.get("usage") or {}).get("duration_ms"))
    social_text = social_result.get("text", "")
    _store(social_result)

    sections: list[str] = []
    if blog_text:
        sections.append(f"## Blog\n\n{blog_text}")
    if social_text:
        sections.append(f"## Social\n\n{social_text}")
    return "\n\n".join(sections), payload_bundle, usage_bundle, warnings
