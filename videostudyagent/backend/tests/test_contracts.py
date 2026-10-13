from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.study import QuizDocument, StudyOptions, Transcript, TranscriptSegment
from app.schemas.tasks import StoredObject, StudyResult, Task


def transcript_data():
    return {
        "source": "subtitle",
        "language": "zh",
        "duration_ms": 3000,
        "segments": [
            {"id": "seg_1", "start_ms": 0, "end_ms": 2000, "text": "学习率控制步长。"},
            {"id": "seg_2", "start_ms": 1500, "end_ms": 3000, "text": "保留负号 -1。"},
        ],
    }


def quiz_data(count=1, difficulty="medium"):
    return {
        "question_count": count,
        "difficulty": difficulty,
        "questions": [
            {
                "id": f"q_{index}",
                "difficulty": difficulty,
                "chapter_id": "ch_1",
                "question": "学习率控制什么？",
                "answer": "更新步长。",
                "explanation": "原文给出定义。",
                "source_segment_ids": ["seg_1"],
                "evidence": [{"segment_id": "seg_1", "quote": "学习率控制步长。"}],
            }
            for index in range(count)
        ],
    }


@pytest.mark.parametrize("count", [1, 5, 20])
@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_options_and_quiz_round_trip(count, difficulty):
    options = StudyOptions(question_count=count, difficulty=difficulty)
    assert options.question_count == count
    quiz = QuizDocument.model_validate(quiz_data(count, difficulty))
    assert QuizDocument.model_validate_json(quiz.model_dump_json()) == quiz


@pytest.mark.parametrize("count", [0, 21, -1, "5", 1.5, True])
def test_reject_invalid_question_counts(count):
    with pytest.raises(ValidationError):
        StudyOptions(question_count=count)


@pytest.mark.parametrize(
    "overrides",
    [
        {"difficulty": "expert"},
        {"question_type": "multiple_choice"},
        {"output_language": ""},
        {"question_count": 5, "extra": "ignored?"},
    ],
)
def test_reject_invalid_options(overrides):
    with pytest.raises(ValidationError):
        StudyOptions(**overrides)


def test_options_are_frozen():
    options = StudyOptions()
    with pytest.raises(ValidationError):
        options.question_count = 10


def test_valid_overlapping_segments_and_partial_result():
    transcript = Transcript.model_validate(transcript_data())
    result = StudyResult(task_id=uuid4(), transcript=transcript)
    assert result.notes is None and result.quiz is None
    assert Transcript.model_validate_json(transcript.model_dump_json()) == transcript


@pytest.mark.parametrize(
    "start,end,text",
    [
        (-1, 100, "text"),
        (100, 100, "text"),
        (200, 100, "text"),
        (0, 1.5, "text"),
        (False, 100, "text"),
        (0, 100, "   "),
    ],
)
def test_reject_invalid_timestamps_or_empty_text(start, end, text):
    with pytest.raises(ValidationError):
        TranscriptSegment(id="seg_1", start_ms=start, end_ms=end, text=text)


@pytest.mark.parametrize("case", ["duplicate", "unsorted", "out_of_bounds", "empty"])
def test_transcript_collection_constraints(case):
    data = transcript_data()
    if case == "duplicate":
        data["segments"][1]["id"] = "seg_1"
    elif case == "unsorted":
        data["segments"].reverse()
    elif case == "out_of_bounds":
        data["duration_ms"] = 2500
    else:
        data["segments"] = []
    with pytest.raises(ValidationError):
        Transcript.model_validate(data)


@pytest.mark.parametrize("case", ["count", "difficulty", "answer", "explanation", "evidence"])
def test_quiz_rejects_incomplete_or_inconsistent_output(case):
    data = deepcopy(quiz_data())
    if case == "count":
        data["question_count"] = 2
    elif case == "difficulty":
        data["questions"][0]["difficulty"] = "hard"
    elif case == "evidence":
        data["questions"][0]["evidence"][0]["segment_id"] = "seg_2"
    else:
        data["questions"][0][case] = " "
    with pytest.raises(ValidationError):
        QuizDocument.model_validate(data)


@pytest.mark.parametrize("storage_key", ["../file", "/file", "C:/file", "a\\file", "a/../file"])
def test_reject_unsafe_storage_keys(storage_key):
    with pytest.raises(ValidationError):
        StoredObject(storage_key=storage_key, sha256="a" * 64)


def test_task_requires_aware_time_and_known_status():
    data = {
        "id": str(uuid4()),
        "title": "课程",
        "options": {},
        "created_at": "2026-10-13T00:00:00Z",
    }
    assert Task.model_validate(data).status == "queued"
    for overrides in ({"created_at": "2026-10-13T00:00:00"}, {"status": "done"}):
        with pytest.raises(ValidationError):
            Task.model_validate(data | overrides)
