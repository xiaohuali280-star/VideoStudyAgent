import asyncio

import pytest

from app.core.errors import StudyError
from app.db.study_repository import StudyRepository
from app.schemas.study import Transcript
from app.services.generation import GenerationService
from app.services.operations import run_operation
from tests.scripted_llm import ScriptedStudyModel
from tests.test_generation import prepared


@pytest.mark.parametrize("corrupt", [False, True])
def test_partial_notes_survive_failure_resume_and_corruption(application, corrupt):
    text = "1\n00:00:00,000 --> 00:00:10,000\n" + ("梯度下降 rate -0.1, " * 1700) + "课程末尾\n"
    task, repo = prepared(application, text=text)

    class FailSecond(ScriptedStudyModel):
        async def complete(self, request):
            if len(self.requests) == 1:
                raise StudyError("LLM_TIMEOUT", "测试中断。", 503, True)
            return await super().complete(request)

    service = GenerationService(application.state.settings, repo, FailSecond())
    with pytest.raises(StudyError):
        asyncio.run(service.generate_notes(task))
    assert not any(a.kind == "notes" for a in repo.artifacts(task.id))
    files = list(application.state.settings.data_dir.rglob("note-parts/*.json"))
    assert len(files) == 1
    if corrupt:
        files[0].write_bytes(b"corrupt checkpoint")
    resumed = ScriptedStudyModel()
    svc = GenerationService(application.state.settings, repo, resumed)
    asyncio.run(svc.generate_notes(task))
    assert len(resumed.requests) == len(
        svc._chunks(
            task,
            svc.store.read_json(
                svc._artifact(task, "transcript"),
                Transcript,
            ),
        )
    ) - (0 if corrupt else 1)


def test_preflight_blocks_before_generation_and_persists_usage(application):
    task, repo = prepared(application)
    model = ScriptedStudyModel()
    settings = application.state.settings.model_copy(update={"llm_total_tokens": 1})
    with pytest.raises(StudyError, match="BUDGET_PREFLIGHT"):
        asyncio.run(GenerationService(settings, repo, model).generate_notes(task))
    assert not model.requests
    study = StudyRepository(repo.engine)
    op = study.claim_next()
    asyncio.run(run_operation(op, application.state.settings, repo, ScriptedStudyModel()))
    usage = study.operation(task.id, op.id).usage
    assert usage.requests_reserved > 0 and usage.tokens_reserved > 0
    assert usage.input_tokens is None  # no provider usage in the offline fixture


def test_model_language_and_preferences_invalidate_note_cache(application):
    task, repo = prepared(application)
    settings = application.state.settings
    first = ScriptedStudyModel()
    asyncio.run(GenerationService(settings, repo, first).generate_notes(task))
    changed = ScriptedStudyModel()
    asyncio.run(
        GenerationService(
            settings.model_copy(update={"llm_model": "test-other"}), repo, changed
        ).generate_notes(task)
    )
    assert len(changed.requests) == 1
    repo.note_preferences = {"detail": "concise"}
    preferences = ScriptedStudyModel()
    asyncio.run(GenerationService(settings, repo, preferences).generate_notes(task))
    assert len(preferences.requests) == 1
    language = ScriptedStudyModel()
    task = task.model_copy(
        update={"options": task.options.model_copy(update={"output_language": "en"})}
    )
    asyncio.run(GenerationService(settings, repo, language).generate_notes(task))
    assert len(language.requests) == 1
