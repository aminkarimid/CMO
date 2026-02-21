import importlib
import sys


def _load_app_module():
    if "app" in sys.modules:
        return sys.modules["app"]
    return importlib.import_module("app")


def test_default_inputs_include_template_safe_keys():
    app = _load_app_module()
    inputs = app.default_inputs()
    required = {
        "preferred_title",
        "angle_choice",
        "campaign_outputs",
        "paid_ads_copy",
        "analytics_summary",
        "distribution_plan",
        "design_brief",
    }
    assert required.issubset(set(inputs.keys()))


def test_extract_task_placeholders_covers_optional_fields():
    app = _load_app_module()
    placeholders = app.extract_task_placeholders()
    assert "preferred_title" in placeholders
    assert "angle_choice" in placeholders


def test_run_builder_instance_recovers_missing_template_variable_once():
    app = _load_app_module()

    class _StubResult:
        output = "ok"
        token_usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}

        def to_dict(self):
            return {"output": "ok"}

    class _StubCrewInstance:
        def __init__(self):
            self.calls = 0

        def kickoff(self, inputs):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                raise ValueError(
                    "Missing required template variable "
                    "'Template variable 'preferred_title' not found in inputs dictionary' in description"
                )
            assert "preferred_title" in inputs
            return _StubResult()

    class _StubCrewFactory:
        def __init__(self):
            self.instance = _StubCrewInstance()

        def blog_crew(self):
            return self.instance

    crew = _StubCrewFactory()
    result = app.run_builder_instance(
        crew=crew,
        builder_name="blog_crew",
        label="Blog",
        base_inputs={"topic": "x3p topic"},
        variant_count=1,
    )

    assert result["text"] == "ok"
    assert "Recovered missing input key 'preferred_title'" in (result.get("warning") or "")
    assert crew.instance.calls == 2
