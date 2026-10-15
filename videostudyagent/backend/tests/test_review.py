import asyncio
import json
from uuid import uuid4

import pytest

from app.adapters.grounding import validate_quiz
from app.core.errors import StudyError
from app.db.review_repository import ReviewRepository, require_approved
from app.db.study_repository import StudyRepository
from app.schemas.iteration import GenerateQuizRequest
from app.schemas.providers import ModelReply
from app.services.generation import GenerationService
from app.services.operations import run_operation
from app.services.review import ReviewService, SourceScopeResolver
from app.services.review_runtime import review_candidate
from app.services.study_versions import VersionReader
from tests.scripted_llm import ScriptedStudyModel
from tests.test_upload_persistence import upload


class CriticModel(ScriptedStudyModel):
    def __init__(self, verdicts=()):
        super().__init__()
        self.verdicts = list(verdicts)

    async def complete(self, request):
        if not request.tools:
            payload = json.loads(request.messages[1].content)
            schema, data = payload["schema"]["title"], payload["course_data"]
            if schema == "ReviewVerdict":
                self.requests.append(request)
                verdict = self.verdicts.pop(0) if self.verdicts else {"status": "passed"}
                return ModelReply(content=json.dumps(verdict))
            if schema == "QuestionV11":
                self.requests.append(request)
                return ModelReply(
                    content=json.dumps(data["original"] | {"answer": "corrected answer"})
                )
        return await super().complete(request)


def setup_review(application, *, limit=100):
    task_id = upload(application).json()["id"]
    repository = application.state.repository
    study = StudyRepository(repository.engine)
    asyncio.run(
        run_operation(
            study.claim_next(), application.state.settings, repository, ScriptedStudyModel()
        )
    )
    state = study.state(task_id)
    reader = VersionReader(application.state.settings.data_dir)
    transcript = reader.transcript(study.snapshot(task_id, state.transcript_snapshot_id))
    notes = reader.notes(study.notes(task_id, state.notes_revision_id))
    quiz = reader.quiz(study.batch(task_id, state.quiz_batch_id))
    request = GenerateQuizRequest(
        transcript_snapshot_id=state.transcript_snapshot_id,
        notes_revision_id=state.notes_revision_id,
        review_policy="semantic",
    )
    from app.schemas.iteration import OperationUsage

    study.enqueue(task_id, request, "review-test", usage=OperationUsage(request_limit=limit))
    operation = study.claim_next()
    settings = application.state.settings.model_copy(update={"llm_max_requests": limit})
    return repository, study, operation, settings, transcript, notes, quiz, state


def failed(target):
    return dict(
        status="failed",
        issues=[
            dict(
                target_id=target, type="unsupported_answer", suggestion="原文引用正确，但答案错误。"
            )
        ],
    )


def test_valid_quote_wrong_answer_one_targeted_repair_keeps_other_four(application):
    repository, study, operation, settings, source, notes, quiz, state = setup_review(application)
    quiz.questions[0].answer = "wrong answer"
    unchanged = [q.model_dump() for q in quiz.questions[1:]]
    model = CriticModel([failed(quiz.questions[0].id), dict(status="passed")])
    service = GenerationService(settings, repository, model)
    corrected, approval = asyncio.run(
        review_candidate(
            operation,
            quiz,
            source,
            state.transcript_snapshot_id,
            service,
            lambda d: validate_quiz(d, source, notes, repository.get(operation.task_id).options),
        )
    )
    assert corrected.questions[0].answer == "corrected answer"
    assert [q.model_dump() for q in corrected.questions[1:]] == unchanged
    assert len(model.requests) == 3 and approval["review_policy"] == "semantic"
    restarted = CriticModel()
    restored, _ = asyncio.run(
        review_candidate(
            operation,
            quiz,
            source,
            state.transcript_snapshot_id,
            GenerationService(settings, repository, restarted),
            lambda d: validate_quiz(d, source, notes, repository.get(operation.task_id).options),
        )
    )
    assert restored == corrected and not restarted.requests
    reports = ReviewRepository(repository.engine).reports(operation.task_id, operation.id)
    assert sorted(r.round for r in reports) == [0, 1]
    assert not ReviewRepository(repository.engine).claim_repair(operation.task_id, operation.id)
    assert study.state(operation.task_id) == state


@pytest.mark.parametrize("mode", ["failed_twice", "malformed", "budget"])
def test_failed_uncertain_budget_preserve_old_formal_results(application, mode):
    repository, study, operation, settings, source, notes, quiz, state = setup_review(
        application, limit=2 if mode == "budget" else 100
    )
    verdicts = [{}, {}] if mode == "malformed" else [failed(quiz.questions[0].id)] * 2
    model = CriticModel(verdicts)
    service = GenerationService(settings, repository, model)
    with pytest.raises(StudyError) as caught:
        asyncio.run(
            review_candidate(
                operation,
                quiz,
                source,
                state.transcript_snapshot_id,
                service,
                lambda d: validate_quiz(
                    d, source, notes, repository.get(operation.task_id).options
                ),
            )
        )
    expected = {
        "failed_twice": "REVIEW_FAILED",
        "malformed": "REVIEW_UNCERTAIN",
        "budget": "AGENT_LIMIT_EXCEEDED",
    }[mode]
    assert caught.value.code == expected
    assert study.state(operation.task_id) == state
    assert len(model.requests) <= 3


def test_hard_failure_cannot_be_overruled_and_cache_rechecks(application):
    repository, study, operation, settings, source, notes, quiz, state = setup_review(application)
    model = CriticModel()
    service = GenerationService(settings, repository, model)
    scope = SourceScopeResolver(operation.task_id, state.transcript_snapshot_id, source)

    def invalid(value):
        raise ValueError("Forged source")

    report = asyncio.run(ReviewService(repository, service).assess(operation, quiz, scope, invalid))
    assert report.status == "failed" and not model.requests
    # Review is bound to exact content, source and operation; metadata cannot approve another file.
    record = study.batch(operation.task_id, state.quiz_batch_id)
    forged = record.model_copy(
        update={
            "review_policy": "semantic",
            "review_report_id": report.id,
            "operation_id": operation.id,
            "sha256": "0" * 64,
        }
    )
    with (
        repository.engine.connect() as connection,
        pytest.raises(StudyError, match="REVIEW_REQUIRED"),
    ):
        require_approved(connection, forged)


def test_forged_reviewer_quote_and_unknown_target_are_uncertain(application):
    repository, study, operation, settings, source, notes, quiz, state = setup_review(application)
    verdict = failed(quiz.questions[0].id)
    verdict["issues"][0]["source_refs"] = [
        dict(
            task_id=str(uuid4()),
            snapshot_id=str(state.transcript_snapshot_id),
            source_type="transcript",
            source_id=source.segments[0].id,
            quote=source.segments[0].text,
        )
    ]
    model = CriticModel([verdict, verdict])
    with pytest.raises(StudyError, match="REVIEW_UNCERTAIN"):
        asyncio.run(
            review_candidate(
                operation,
                quiz,
                source,
                state.transcript_snapshot_id,
                GenerationService(settings, repository, model),
                lambda d: None,
            )
        )
