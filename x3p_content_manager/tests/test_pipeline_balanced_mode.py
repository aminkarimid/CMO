import importlib
import sys
import time

import pytest

import x3p_content_manager.app.pipeline as pipeline_mod


def _load_app_module():
    if "app" in sys.modules:
        return sys.modules["app"]
    return importlib.import_module("app")


def test_blog_pipeline_triggers_single_reedit_on_major(monkeypatch):
    app = _load_app_module()
    counts = {"blog": 0, "fact": 0, "brand": 0, "editor": 0}

    def _stub_run_builder_instance(crew, builder_name, label, inputs, variant_count=1):  # noqa: ANN001
        if builder_name == "blog_crew":
            counts["blog"] += 1
            return {"label": "Blog", "text": "draft blog", "payload": {"output": "draft blog"}, "usage": {"duration_ms": 1}}
        if builder_name == "factcheck_crew":
            counts["fact"] += 1
            sev = "MAJOR" if counts["fact"] == 1 else "NONE"
            text = f'{{"severity":"{sev}","issues":1,"summary":"stub"}}\nreport'
            return {"label": "Fact-check", "text": text, "payload": {"output": text}, "usage": {"duration_ms": 1}}
        if builder_name == "brandcheck_crew":
            counts["brand"] += 1
            text = '{"severity":"NONE","issues":0,"summary":"ok"}\nreport'
            return {"label": "Brand Check", "text": text, "payload": {"output": text}, "usage": {"duration_ms": 1}}
        if builder_name == "editor_crew":
            counts["editor"] += 1
            return {"label": "Blog (Re-Edit)", "text": "edited blog", "payload": {"output": "edited blog"}, "usage": {"duration_ms": 1}}
        raise AssertionError(f"Unexpected builder: {builder_name}")

    monkeypatch.setattr(pipeline_mod, "run_builder_instance", _stub_run_builder_instance)
    inputs = app.build_template_safe_inputs({"topic": "x3p", "audience": "users", "tone": "clear", "key_facts": []})
    text, payload, usage, warnings = pipeline_mod.run_pipeline_with_quality_gate(
        crew=object(),
        pipeline="Blog",
        inputs=inputs,
        variants=1,
        progress=None,
    )

    assert text == "edited blog"
    assert counts["editor"] == 1
    assert counts["fact"] == 1
    assert counts["brand"] == 1
    assert any("one-time blog re-edit" in w for w in warnings)
    assert "Blog (Re-Edit)" in payload
    assert "Blog (Re-Edit)" in usage


def test_social_pipeline_keeps_initial_output_if_rerun_empty(monkeypatch):
    app = _load_app_module()
    counts = {"social": 0, "fact": 0, "brand": 0}

    def _stub_run_builder_instance(crew, builder_name, label, inputs, variant_count=1):  # noqa: ANN001
        if builder_name == "social_crew":
            counts["social"] += 1
            text = "initial social output" if counts["social"] == 1 else ""
            return {"label": "Social", "text": text, "payload": {"output": text}, "usage": {"duration_ms": 1}}
        if builder_name == "factcheck_crew":
            counts["fact"] += 1
            sev = "MAJOR" if counts["fact"] == 1 else "NONE"
            text = f'{{"severity":"{sev}","issues":1,"summary":"stub"}}\nreport'
            return {"label": "Fact-check", "text": text, "payload": {"output": text}, "usage": {"duration_ms": 1}}
        if builder_name == "brandcheck_crew":
            counts["brand"] += 1
            text = '{"severity":"NONE","issues":0,"summary":"ok"}\nreport'
            return {"label": "Brand Check", "text": text, "payload": {"output": text}, "usage": {"duration_ms": 1}}
        raise AssertionError(f"Unexpected builder: {builder_name}")

    monkeypatch.setattr(pipeline_mod, "run_builder_instance", _stub_run_builder_instance)
    monkeypatch.setattr(
        pipeline_mod,
        "_run_trend_intel_stage",
        lambda inputs: {
            "label": "Trend Intel",
            "text": '{"ok": true}',
            "payload": {"kept_claims": [{"claim": "x"}], "dropped_claims": []},
            "usage": {"duration_ms": 1},
            "warning": None,
        },
    )
    inputs = app.build_template_safe_inputs({"topic": "x3p", "audience": "users", "tone": "clear", "key_facts": []})
    text, payload, usage, warnings = pipeline_mod.run_pipeline_with_quality_gate(
        crew=object(),
        pipeline="Social",
        inputs=inputs,
        variants=1,
        progress=None,
    )

    assert text == "initial social output"
    assert counts["social"] == 2
    assert counts["fact"] == 1
    assert counts["brand"] == 1
    assert "Trend Intel" in payload
    assert any("kept initial social draft" in w for w in warnings)
    assert "Social" in payload
    assert "Social" in usage


def test_social_pipeline_fails_when_trend_intel_has_no_verified_claims(monkeypatch):
    app = _load_app_module()
    monkeypatch.setattr(
        pipeline_mod,
        "_run_trend_intel_stage",
        lambda inputs: (_ for _ in ()).throw(pipeline_mod.StageDependencyError("No trend claims passed strict verification")),
    )

    with pytest.raises(pipeline_mod.StageDependencyError):
        pipeline_mod.run_pipeline_with_quality_gate(
            crew=object(),
            pipeline="Social",
            inputs=app.build_template_safe_inputs({"topic": "x3p", "audience": "users", "tone": "clear"}),
            variants=1,
            progress=None,
        )


def test_run_builder_instance_timeout_raises_stage_timeout(monkeypatch):
    app = _load_app_module()

    class _FailingCrew:
        def kickoff(self, inputs):  # noqa: ANN001
            raise TimeoutError("Social exceeded 30s timeout")

    class _Factory:
        def social_crew(self):
            return _FailingCrew()

    with pytest.raises(pipeline_mod.StageTimeoutError):
        app.run_builder_instance(
            crew=_Factory(),
            builder_name="social_crew",
            label="Social",
            base_inputs={"topic": "x3p", "audience": "users"},
            variant_count=1,
        )


def test_build_template_safe_inputs_handles_missing_optional_keys():
    app = _load_app_module()
    safe = app.build_template_safe_inputs({"topic": "x3p"})
    assert safe["preferred_title"] == ""
    assert safe["angle_choice"] == ""
    assert safe["trend_brief"] == ""
    assert safe["brand_snapshot"] == ""


def test_run_builder_instance_fails_fast_on_backend_error():
    app = _load_app_module()

    class _FailingCrew:
        def kickoff(self, inputs):  # noqa: ANN001
            raise RuntimeError("APIConnectionError: OllamaException - [Errno 1] Operation not permitted")

    class _Factory:
        def social_crew(self):
            return _FailingCrew()

    with pytest.raises(pipeline_mod.BackendUnavailableError):
        app.run_builder_instance(
            crew=_Factory(),
            builder_name="social_crew",
            label="Social",
            base_inputs={"topic": "x3p", "audience": "users"},
            variant_count=1,
        )


def test_run_builder_instance_fails_fast_on_runtime_config_error():
    app = _load_app_module()

    class _FailingCrew:
        def kickoff(self, inputs):  # noqa: ANN001
            raise RuntimeError(
                "ValidationError: 1 validation error for Crew\nmemory\n  Input should be a valid boolean"
            )

    class _Factory:
        def social_crew(self):
            return _FailingCrew()

    with pytest.raises(pipeline_mod.RuntimeConfigurationError):
        app.run_builder_instance(
            crew=_Factory(),
            builder_name="social_crew",
            label="Social",
            base_inputs={"topic": "x3p", "audience": "users"},
            variant_count=1,
        )


def test_run_builder_instance_timeout_does_not_block_until_worker_finishes(monkeypatch):
    app = _load_app_module()

    class _SlowCrew:
        def kickoff(self, inputs):  # noqa: ANN001
            time.sleep(2.0)
            return {"output": "late"}

    class _Factory:
        def social_crew(self):
            return _SlowCrew()

    monkeypatch.setattr(pipeline_mod, "_step_timeout_seconds", lambda: 1)
    start = time.perf_counter()
    with pytest.raises(pipeline_mod.StageTimeoutError):
        app.run_builder_instance(
            crew=_Factory(),
            builder_name="social_crew",
            label="Social",
            base_inputs={"topic": "x3p", "audience": "users"},
            variant_count=1,
        )
    elapsed = time.perf_counter() - start

    assert elapsed < 1.6
