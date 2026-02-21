import json
from pathlib import Path

import pytest

import x3p_content_manager.main as main_mod


class _StubResult:
    def __init__(self):
        self.output = "stub output"
        self.token_usage = {
            "prompt_tokens": 40,
            "completion_tokens": 59,
            "total_tokens": 99,
        }

    def to_dict(self):
        return {"output": self.output}


class _StubCrew:
    def kickoff(self, inputs):  # type: ignore[no-untyped-def]
        assert "topic" in inputs
        return _StubResult()


class _FakeCrewFactory:
    def __getattr__(self, name):  # type: ignore[no-untyped-def]
        if name.endswith("_crew"):
            def _builder():  # type: ignore[no-untyped-def]
                return _StubCrew()

            return _builder
        raise AttributeError(name)


@pytest.mark.parametrize(
    ("builder", "mode", "label"),
    [
        ("blog_crew", "blog", "blog pipeline"),
        ("social_crew", "social", "social media pipeline"),
        ("full_crew", "all", "FULL X3P content pipeline"),
    ],
)
def test_execute_pipeline_creates_artifacts(monkeypatch, tmp_path, builder, mode, label):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main_mod, "X3PCareContentCrew", _FakeCrewFactory)

    result = main_mod._execute_pipeline(builder, mode, label)

    assert isinstance(result, _StubResult)
    runs_dir = Path("runs")
    json_files = list(runs_dir.glob(f"{mode}_*.json"))
    assert len(json_files) == 1
    saved = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert saved.get("output") == "stub output"

    telemetry_path = runs_dir / "telemetry.log"
    assert telemetry_path.exists()
    entries = telemetry_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(entries) == 1
    payload = json.loads(entries[0])
    assert payload["pipeline"] == mode
    assert payload["success"] is True
    assert payload["tokens"] == {
        "prompt_tokens": 40,
        "completion_tokens": 59,
        "total_tokens": 99,
    }
