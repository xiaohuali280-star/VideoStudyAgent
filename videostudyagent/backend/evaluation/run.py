"""Offline-only CLI; explicit directories, no Settings(), keys, DB, or network."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from evaluation.contracts import CaseResult, EvaluationCase, EvaluationRun
from evaluation.metrics import evaluate


def run(suite: Path, output: Path, mode="fixture", capabilities=(), git_sha=None):
    suite = suite.resolve(strict=True)
    results, digest = [], hashlib.sha256()
    for path in sorted(suite.glob("*.case.json")):
        raw = path.read_bytes()
        case = EvaluationCase.model_validate_json(raw)
        digest.update(raw)
        if len(case.fixture_refs) != 1:
            raise ValueError("Exactly one fixture required")
        relative = Path(case.fixture_refs[0])
        source = (suite / relative).resolve(strict=True)
        if relative.is_absolute() or not source.is_relative_to(suite):
            raise ValueError("Fixture path must stay within suite")
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != case.input_sha256:
            raise ValueError("Fixture hash mismatch")
        digest.update(data)
        missing = sorted(set(case.capabilities_required) - set(capabilities))
        if missing:
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    execution_status="pending_capability",
                    missing_capabilities=missing,
                )
            )
            continue
        assertions, metrics = evaluate(
            json.loads(data), "synthetic_fixture" if mode == "fixture" else "replay"
        )
        passed = all(
            assertions.get(key) == value for key, value in case.expected_assertions.items()
        )
        results.append(
            CaseResult(
                case_id=case.case_id,
                execution_status="passed" if passed else "failed",
                assertions=assertions,
                metrics=metrics,
            )
        )
    report = EvaluationRun(
        run_id=str(uuid4()),
        project_git_sha=git_sha,
        suite_sha256=digest.hexdigest(),
        mode=mode,
        capabilities=sorted(capabilities),
        started_at=datetime.now(UTC).isoformat(),
        case_results=results,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fixture", "replay"], required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.suite, args.output, args.mode)


if __name__ == "__main__":
    main()
