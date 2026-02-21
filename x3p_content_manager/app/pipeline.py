from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from x3p_content_manager.app.input_contract import PIPELINES
from x3p_content_manager.app.template_guard import extract_missing_template_var
from x3p_content_manager.crew import X3PCareContentCrew
from x3p_content_manager.utils import extract_token_usage

LABEL_TO_CONTEXT_KEY = {
    "Blog": "blog_post",
    "Social": "social_outputs",
    "Fact-check": "factcheck_report",
    "Brand Check": "brand_report",
}

LABEL_TO_AGENT = {
    "Blog": "Strategist + Writer + Editor",
    "Blog (Re-Edit)": "Editor",
    "Social": "Social Media Manager",
    "Fact-check": "Fact Checker",
    "Brand Check": "Brand Guardian",
}

QUOTA_ERROR_INDICATORS = ("quota", "rate limit", "429", "ratelimiterror", "quota exceeded")
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
RUNTIME_CONFIG_ERROR_INDICATORS = (
    "validation error for crew",
    "input should be a valid boolean",
    "\nmemory\n",
)


class BackendUnavailableError(RuntimeError):
    """Raised when the configured LLM backend is unavailable."""


class RuntimeConfigurationError(RuntimeError):
    """Raised when app/crew runtime wiring is inconsistent and needs refresh."""


def _step_timeout_seconds() -> int:
    env = str(os.getenv("X3P_STEP_TIMEOUT_SEC", "")).strip()
    if env.isdigit():
        return max(15, int(env))
    return 30


def is_quota_error(exc: Exception | str) -> bool:
    return any(tok in str(exc).lower() for tok in QUOTA_ERROR_INDICATORS)


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


def is_runtime_configuration_error(exc: Exception | str) -> bool:
    msg = str(exc).lower()
    if all(h in msg for h in RUNTIME_CONFIG_ERROR_INDICATORS):
        return True
    return "validation error for crew" in msg and "memory" in msg and "valid boolean" in msg


def _log_error(msg: str) -> None:
    try:
        os.makedirs("runs", exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("runs/errors.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def build_mock_blog_content(topic: str, audience: str | None = None) -> str:
    audience_label = audience or "general audience"
    return (
        f"# {topic}\n\n"
        "### Opportunity Gap\n"
        f"The care economy continues to face workforce instability affecting {audience_label}. "
        "Many employers struggle with retention while workers struggle with predictable, quality opportunities.\n\n"
        "### How X3P Builds Good Jobs\n"
        "X3P helps connect workers to better opportunities with structured pathways, employer alignment, and practical support. "
        "The focus is on dignity, stability, and growth.\n\n"
        "### Outcomes & Partnerships\n"
        "Early partner programs show stronger alignment between worker expectations and employer needs. "
        "Where hard metrics are not yet verified, X3P uses conservative language and evidence-first messaging.\n\n"
        "**Call to Action**\n"
        "To explore partnership or placement pathways, Visit x3p.ai or contact partnerships@x3p.ai.\n\n"
        "## Sources\n"
        "- Evidence pending verification — [X3P](https://x3p.ai)\n\n"
        "---\n"
        "*Fallback draft generated due to backend or quota constraints.*"
    )


def build_mock_social_content(topic: str, audience: str | None = None) -> str:
    aud = audience or "your audience"
    return (
        "## LinkedIn post 1\n"
        f"Good jobs are a growth strategy, not just a hiring tactic. For {aud}, stronger role quality can improve retention and trust. Visit x3p.ai\n"
        "Hashtags: #GoodJobs #Workforce\n\n"
        "## LinkedIn post 2\n"
        f"When talent pathways are clear, outcomes improve for workers and employers. {topic} is a practical way to frame this shift. Visit x3p.ai\n"
        "Hashtags: #CareEconomy #Hiring\n\n"
        "## Facebook post 1\n"
        "Communities thrive when people can access stable, dignified work. X3P helps turn that into action with partner-ready pathways. Visit x3p.ai\n"
        "Hashtags: #Community #GoodJobs\n\n"
        "## Facebook post 2\n"
        "A better workforce story starts with better job quality. X3P supports partners and workers with practical steps that can scale. Visit x3p.ai\n"
        "Hashtags: #WorkforceDevelopment #X3P\n\n"
        "## Instagram caption 1\n"
        "Good jobs create momentum for workers, families, and employers. X3P is building pathways that keep quality and access at the center. Visit x3p.ai\n"
        "Suggested visual: Team collaboration with care workers and partner organizations\n"
        "Hashtags: #GoodJobs #CareWork\n\n"
        "## Instagram caption 2\n"
        "Care pathways should feel possible, not distant. X3P helps connect people to structured opportunities with clear next steps. Visit x3p.ai\n"
        "Suggested visual: Career pathway graphic with milestone steps\n"
        "Hashtags: #CareerPathways #X3P"
    )


def _fallback_text_for_label(label: str, topic: str, audience: str) -> str:
    if label in {"Fact-check", "Brand Check"}:
        check = "fact-check" if label == "Fact-check" else "brand-check"
        header = json.dumps({"severity": "MINOR", "issues": 1, "summary": f"{check} timed out"}, ensure_ascii=False)
        return f"{header}\nAutomatic fallback: {check} step timed out. Review before publishing."
    if label == "Social":
        return build_mock_social_content(topic, audience)
    return build_mock_blog_content(topic, audience)


def to_serializable(result: Any) -> tuple[str, Any]:
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
    m = re.match(r"^---\s*\n(.*?)\n---", md_text, flags=re.DOTALL)
    if not m:
        return md_text
    fm = m.group(1)
    if re.search(r"(?m)^title:\s*", fm):
        fm = re.sub(r"(?m)^title:\s*.*$", f'title: "{title}"', fm)
    else:
        fm = f'title: "{title}"\n{fm}'

    slug = _slugify(title)
    if re.search(r"(?m)^slug:\s*", fm):
        fm = re.sub(r"(?m)^slug:\s*.*$", f"slug: {slug}", fm)
    else:
        fm = f"slug: {slug}\n{fm}"
    return md_text.replace(m.group(0), f"---\n{fm}\n---", 1)


def _inject_angle_in_yaml(md_text: str, angle: str | None) -> str:
    if not md_text or not angle:
        return md_text
    m = re.match(r"^---\s*\n(.*?)\n---", md_text, flags=re.DOTALL)
    if not m:
        return md_text
    fm = m.group(1)
    if "tags:" not in fm:
        fm = f"tags:\n  - {angle}\n{fm}"
    elif angle.lower() not in fm.lower():
        fm = re.sub(r"(?m)^tags:\s*$", f"tags:\n  - {angle}", fm)
    return md_text.replace(m.group(0), f"---\n{fm}\n---", 1)


def run_builder_instance(
    crew: X3PCareContentCrew,
    builder_name: str,
    label: str,
    base_inputs: dict,
    variant_count: int = 1,
) -> dict[str, Any]:
    local_inputs = copy.deepcopy(base_inputs)
    timeout_sec = _step_timeout_seconds()
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
            except BaseException as exc:  # pragma: no cover - passthrough bucket
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
                text, payload = to_serializable(response)
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
            text, payload = to_serializable(response)
            result["text"] = text
            result["payload"] = payload
    except Exception as exc:
        topic = local_inputs.get("topic", "X3P overview") or "X3P overview"
        audience = local_inputs.get("audience", "general audience") or "general audience"

        if is_runtime_configuration_error(exc):
            _log_error(f"{label} runtime configuration error: {type(exc).__name__}: {exc}")
            raise RuntimeConfigurationError(f"{label} runtime configuration error: {exc}") from exc
        if is_backend_unavailable_error(exc):
            _log_error(f"{label} backend unavailable: {type(exc).__name__}: {exc}")
            raise BackendUnavailableError(f"{label} backend unavailable: {exc}") from exc
        if is_quota_error(exc):
            _log_error(f"{label} quota/runtime error: {type(exc).__name__}: {exc}")
            fallback = _fallback_text_for_label(label, topic, audience)
            result.update(
                {
                    "text": fallback,
                    "payload": {"output": fallback, "mock": True, "reason": "quota"},
                    "usage": {},
                    "mock": True,
                    "warning": f"Quota limits hit while running {label}.",
                }
            )
        elif isinstance(exc, TimeoutError) or is_transient_runtime_error(exc):
            _log_error(f"{label} timeout/transient error: {type(exc).__name__}: {exc}")
            fallback = _fallback_text_for_label(label, topic, audience)
            result.update(
                {
                    "text": fallback,
                    "payload": {
                        "output": fallback,
                        "mock": True,
                        "reason": "timeout_or_connection_error",
                        "step_timeout_sec": timeout_sec,
                    },
                    "usage": {},
                    "mock": True,
                    "warning": f"{label} timed out or had unstable connectivity; fallback content was used.",
                }
            )
        else:
            _log_error(f"{label} internal runtime error: {type(exc).__name__}: {exc}")
            fallback = _fallback_text_for_label(label, topic, audience)
            result.update(
                {
                    "text": fallback,
                    "payload": {
                        "output": fallback,
                        "mock": True,
                        "reason": "step_runtime_error",
                        "error_type": type(exc).__name__,
                    },
                    "usage": {},
                    "mock": True,
                    "warning": f"{label} encountered an internal runtime issue; fallback content was used.",
                }
            )
    finally:
        local_inputs.pop("variant", None)

    duration_ms = int((time.perf_counter() - start) * 1000)
    usage = result.get("usage") or {}
    if isinstance(usage, dict):
        usage["duration_ms"] = duration_ms
    else:
        usage = {"duration_ms": duration_ms}
    result["usage"] = usage

    if recovery_notes:
        note = " ".join(sorted(set(recovery_notes)))
        if result.get("warning"):
            result["warning"] = f"{result['warning']} {note}".strip()
        else:
            result["warning"] = note

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
            result = future.result()
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
        if progress:
            progress.start("Blog", LABEL_TO_AGENT.get("Blog", ""))
        blog_result = run_builder_instance(crew, "blog_crew", "Blog", inputs, 1)
        if progress:
            progress.done("Blog", ok=True, note=blog_result.get("warning") or "", duration_ms=(blog_result.get("usage") or {}).get("duration_ms"))
        blog_text = _inject_angle_in_yaml(_force_title_in_yaml(blog_result.get("text", ""), inputs.get("preferred_title")), inputs.get("angle_choice"))
        blog_result["text"] = blog_text
        _store_result(blog_result)

        _, _, need_reedit = _run_fact_brand_checks(crew, inputs, progress, payload_bundle, usage_bundle, warnings)
        if need_reedit:
            if progress:
                progress.start("Blog (Re-Edit)", LABEL_TO_AGENT.get("Blog (Re-Edit)", ""))
            reedit = run_builder_instance(crew, "editor_crew", "Blog (Re-Edit)", inputs, 1)
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
        if progress:
            progress.start("Social", LABEL_TO_AGENT.get("Social", ""))
        social_result = run_builder_instance(crew, "social_crew", "Social", inputs, variants)
        if progress:
            progress.done("Social", ok=True, note=social_result.get("warning") or "", duration_ms=(social_result.get("usage") or {}).get("duration_ms"))
        social_text = social_result.get("text", "")
        _store_result(social_result)

        _, _, need_rerun = _run_fact_brand_checks(crew, inputs, progress, payload_bundle, usage_bundle, warnings)
        if need_rerun:
            if progress:
                progress.start("Social", LABEL_TO_AGENT.get("Social", ""))
            rerun = run_builder_instance(crew, "social_crew", "Social", inputs, variants)
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

    def _store(result: dict[str, Any]) -> None:
        label = result.get("label", "")
        payload_bundle[label] = result.get("payload")
        usage_bundle[label] = result.get("usage")
        context_key = LABEL_TO_CONTEXT_KEY.get(label)
        if context_key:
            inputs[context_key] = result.get("text", "") or ""
        if result.get("warning"):
            warnings.append(result["warning"])

    if progress:
        progress.start("Blog", LABEL_TO_AGENT.get("Blog", ""))
    blog_result = run_builder_instance(crew, "blog_crew", "Blog", inputs, 1)
    if progress:
        progress.done("Blog", ok=True, note=blog_result.get("warning") or "", duration_ms=(blog_result.get("usage") or {}).get("duration_ms"))

    blog_text = _inject_angle_in_yaml(_force_title_in_yaml(blog_result.get("text", ""), inputs.get("preferred_title")), inputs.get("angle_choice"))
    blog_result["text"] = blog_text
    _store(blog_result)

    _, _, need_reedit = _run_fact_brand_checks(crew, inputs, progress, payload_bundle, usage_bundle, warnings)
    if need_reedit:
        if progress:
            progress.start("Blog (Re-Edit)", LABEL_TO_AGENT.get("Blog (Re-Edit)", ""))
        reedit = run_builder_instance(crew, "editor_crew", "Blog (Re-Edit)", inputs, 1)
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

    if progress:
        progress.start("Social", LABEL_TO_AGENT.get("Social", ""))
    social_result = run_builder_instance(crew, "social_crew", "Social", inputs, variants)
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
