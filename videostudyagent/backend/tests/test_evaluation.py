import json
from pathlib import Path

import pytest

from evaluation.metrics import ratio
from evaluation.run import run

SUITE = Path(__file__).parents[1] / "evaluation/cases/v1"


def test_frozen_suite_offline_repeatable(tmp_path):
    first = run(SUITE, tmp_path / "first")
    second = run(SUITE, tmp_path / "second")
    assert len(first.case_results) == 12
    assert first.suite_sha256 == second.suite_sha256
    assert first.case_results == second.case_results
    assert all(c.execution_status != "failed" for c in first.case_results)
    assert any(c.execution_status == "pending_capability" for c in first.case_results)
    for case in first.case_results:
        assert all(m.value is None for m in case.metrics if m.name.endswith("_manual"))
    assert first.cost is None


def test_zero_denominator_is_unknown():
    metric = ratio("empty", 0, 0)
    assert metric.value is None and metric.status == "insufficient_data"


def test_replay_validates_generated_notes_and_quiz_not_only_input():
    from evaluation.metrics import evaluate

    payload = json.loads(next(SUITE.glob("*.fixture.json")).read_text("utf-8"))
    for kind in ("notes", "quiz"):
        assertions, metrics = evaluate(
            payload | {"candidate_kind": kind, "candidate": {}}, "replay"
        )
        assert not assertions["schema_valid"]
        assert metrics[0].value == 0
        assert all(m.value is None for m in metrics if m.name.endswith("_manual"))


@pytest.mark.parametrize("mutation", ["path", "hash", "version"])
def test_bad_suite_rejected(tmp_path, mutation):
    case = json.loads(next(SUITE.glob("*.case.json")).read_text("utf-8"))
    if mutation == "path":
        case["fixture_refs"] = ["../outside.json"]
        (tmp_path / "outside.json").write_text("{}")
    elif mutation == "hash":
        case["input_sha256"] = "0" * 64
    else:
        case["suite_version"] = "99"
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "bad.case.json").write_text(json.dumps(case))
    (suite / case["fixture_refs"][0]).write_text("{}")
    with pytest.raises(ValueError):
        run(suite, tmp_path / "report")
