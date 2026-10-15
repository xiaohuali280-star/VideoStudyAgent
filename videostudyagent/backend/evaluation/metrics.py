import json

from pydantic import ValidationError

from app.adapters.grounding import quote_present
from app.schemas.study import Transcript
from app.services.note_documents import NoteReader
from app.services.quiz_documents import QuizReader
from evaluation.contracts import MetricResult


def ratio(name, numerator, denominator, scope="synthetic_fixture"):
    return MetricResult(
        name=name,
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
        status="measured" if denominator else "insufficient_data",
        measurement_scope=scope,
    )


def evaluate(payload, scope="synthetic_fixture"):
    try:
        transcript = Transcript.model_validate(payload["transcript"])
    except (ValidationError, KeyError, TypeError):
        return {"schema_valid": False}, [ratio("schema_valid_rate", 0, 1, scope)]
    sources = {s.id: s for s in transcript.segments}
    schema_valid = True
    if "candidate" in payload:
        try:
            reader = {"notes": NoteReader, "quiz": QuizReader}[payload["candidate_kind"]]
            reader.model_validate_json(json.dumps(payload["candidate"]))
        except (ValueError, KeyError, TypeError):
            schema_valid = False
    assertions = {"schema_valid": schema_valid}
    quotes, times, cited = [], [], set()
    for ref in payload.get("citations", []):
        source = sources.get(ref.get("source_id"))
        owned = ref.get("task_id") == payload.get("task_id")
        quotes.append(bool(source and owned and quote_present(ref.get("quote", ""), source.text)))
        times.append(bool(source and owned and ref.get("start_ms") == source.start_ms))
        if source and owned:
            cited.add(source.id)
    assertions.update(quotes_valid=all(quotes), timestamps_valid=all(times))
    expected = set(payload.get("expected_source_ids", sources))
    metrics = [
        ratio("schema_valid_rate", int(schema_valid), 1, scope),
        ratio("quote_match_rate", sum(quotes), len(quotes), scope),
        ratio("timestamp_valid_rate", sum(times), len(times), scope),
        ratio("source_id_coverage_rate", len(cited & expected), len(expected), scope),
    ]
    metrics += [
        MetricResult(
            name=name,
            status="not_run",
            measurement_scope=scope,
            reason="No independent human review supplied",
        )
        for name in (
            "claim_faithfulness_manual",
            "note_coverage_manual",
            "quiz_answer_correctness_manual",
        )
    ]
    return assertions, metrics
