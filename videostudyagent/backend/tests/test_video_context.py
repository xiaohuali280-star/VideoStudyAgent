import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.errors import StudyError
from app.db.context_repository import VideoContextRepository
from app.db.repository import initialize_database
from app.db.study_repository import StudyRepository
from app.schemas.providers import ModelReply, ToolCall
from app.schemas.video_context import EvidenceFrame, VideoContextSnapshot
from app.services.exports import ResultService
from app.services.operations import run_operation
from app.services.source_context import validate_refs
from app.services.storage import ArtifactStore, file_hash
from app.services.video_context import VideoContextService
from tests.scripted_llm import ScriptedStudyModel
from tests.test_upload_persistence import MP4, SRT, upload


class ContextModel(ScriptedStudyModel):
    async def complete(self, request):
        if request.tools:
            self.requests.append(request)
            state = json.loads(request.messages[-1].content)["state"]
            artifacts = state["artifacts"]
            if "context" not in artifacts:
                name, args = "prepare_video_context", {}
            elif "notes" not in artifacts and state["options"]["generate_notes"]:
                name, args = "generate_notes", {"context_artifact_id": artifacts["context"]}
            elif "quiz" not in artifacts and state["options"]["generate_quiz"]:
                name, args = "generate_quiz", {"context_artifact_id": artifacts["context"]}
            else:
                return ModelReply(content="done")
            self.agent_index += 1
            return ModelReply(
                tool_calls=[ToolCall(id=f"ctx{self.agent_index}", name=name, arguments=args)]
            )
        payload = json.loads(request.messages[1].content)
        data, schema = payload["course_data"], payload["schema"]["title"]
        if schema not in {
            "NotesDocumentV12",
            "QuizDocumentV12",
            "QuizPartV12",
            "ContextChatAnswer",
        }:
            return await super().complete(request)
        self.requests.append(request)
        sources = data.get("source_items", data.get("segments"))
        refs = [
            dict(
                task_id=data["task_id"],
                snapshot_id=data["snapshot_id"],
                source_type=s["source_type"],
                source_id=s["source_id"],
                quote=s["text"],
            )
            for s in sources
        ]
        if schema == "ContextChatAnswer":
            result = dict(answer_markdown="来自原始证据", citations=refs[:1])
        elif schema == "NotesDocumentV12":
            result = dict(
                schema_version="1.2",
                context_snapshot_id=data["snapshot_id"],
                title=data["title"],
                learning_objectives=["理解"],
                key_concepts=["概念"],
                summary="总结",
                chapters=[
                    dict(id="chapter", title="来源", content_markdown="内容 -0.1", source_refs=refs)
                ],
            )
        else:
            result = dict(
                schema_version="1.2",
                context_snapshot_id=data["snapshot_id"],
                difficulty=data["difficulty"],
                question_count=data["question_count"],
                questions=[],
            )
            for _ in range(data["question_count"]):
                self.question_index += 1
                result["questions"].append(
                    dict(
                        id=f"q{self.question_index}",
                        difficulty=data["difficulty"],
                        question=f"问题{self.question_index}",
                        answer="答案",
                        explanation="说明",
                        source_refs=refs[:1],
                    )
                )
        return ModelReply(content=json.dumps(result))


class FakeOCR:
    version, language = "fake-v1", "eng"

    def __init__(self):
        self.calls = 0

    def recognize(self, path):
        self.calls += 1
        return [dict(raw_text="画面 rate -0.1", bbox=(0, 0, 200, 40), confidence=95)]


def prepared_context(application, *, visual=False, notes=True, quiz=True):
    files = {"video": ("lesson.mp4", MP4)} if visual else {"subtitle": ("lesson.srt", SRT)}
    response = upload(
        application,
        files,
        data={
            "options": json.dumps(dict(enable_ocr=True, generate_notes=notes, generate_quiz=quiz))
        },
    )
    assert response.status_code == 202, response.text
    repo = application.state.repository
    return repo.get(response.json()["id"]), repo


def fake_frames(task, asset, settings):
    store, frame_id = ArtifactStore(settings.data_dir, None), uuid4()
    key = f"tasks/{task.id}/frames/{frame_id}.png"
    path = store.path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"self-created-image-fixture")
    return [
        EvidenceFrame(
            id=frame_id,
            task_id=task.id,
            video_asset_sha256=asset.sha256,
            timestamp_ms=1234,
            storage_key=key,
            sha256=file_hash(path),
            width=200,
            height=40,
        )
    ]


def no_audio(*args, **kwargs):
    raise StudyError("NO_AUDIO_TRACK", "无音轨", 422)


def test_subtitle_only_skips_ocr_and_preserves_source(application):
    task, repo = prepared_context(application, notes=False, quiz=False)
    ocr = FakeOCR()
    service = VideoContextService(
        application.state.settings,
        repo,
        ocr=ocr,
        frames=lambda *a: pytest.fail("No video frames expected"),
    )
    artifact = service.prepare_video_context(task)
    context = service.store.read_json(artifact, VideoContextSnapshot)
    assert context.transcript.source == "subtitle"
    assert context.branch_statuses["ocr"] == "disabled" and ocr.calls == 0
    assert VideoContextRepository(repo.engine).get(task.id, context.id) == context


def test_ocr_only_end_to_end_versions_exports_and_source_forgery(application, monkeypatch):
    monkeypatch.setattr("app.services.transcription.TranscriptService.extract_audio", no_audio)
    task, repo = prepared_context(application, visual=True)
    repo.ocr_provider, repo.frame_extractor = FakeOCR(), fake_frames
    study = StudyRepository(repo.engine)
    operation = study.claim_next()
    asyncio.run(run_operation(operation, application.state.settings, repo, ContextModel()))
    assert study.operation(task.id, operation.id).status == "succeeded", study.operation(
        task.id, operation.id
    ).error
    result = ResultService(application.state.settings.data_dir, repo).result(task.id)
    assert result.transcript is None and result.context and result.notes.schema_version == "1.2"
    assert len(result.quiz.questions) == 5 and repo.get(task.id).status == "succeeded"
    assert "ocr 00:00:01" in ResultService(application.state.settings.data_dir, repo).export(
        task.id, "notes.md"
    ).read_text("utf-8")
    with pytest.raises(StudyError, match="RESULT_NOT_READY"):
        ResultService(application.state.settings.data_dir, repo).export(task.id, "transcript.srt")
    ref = result.quiz.questions[0].source_refs[0]
    with pytest.raises(ValueError):
        validate_refs([ref.model_copy(update={"task_id": uuid4()})], result.context)
    with pytest.raises(ValueError):
        validate_refs([ref.model_copy(update={"quote": "0.1"})], result.context)

    from app.schemas.iteration import ChatReplyRequest, NotePreferences, ReviseNotesRequest
    from tests.test_config_health import request

    state = study.state(task.id)
    conversation = study.create_conversation(task.id)
    chat = study.enqueue(
        task.id,
        ChatReplyRequest(
            conversation_id=conversation.id,
            notes_revision_id=state.notes_revision_id,
            chapter_ids=[result.notes.chapters[0].id],
            message="解释负号",
        ),
        "context-chat",
    )
    asyncio.run(run_operation(study.claim_next(), application.state.settings, repo, ContextModel()))
    assert study.operation(task.id, chat.id).status == "succeeded"
    assert study.messages(task.id, conversation.id)[-1].citations[0].source_type == "ocr"
    revise = study.enqueue(
        task.id,
        ReviseNotesRequest(
            context_snapshot_id=result.context.id,
            base_revision_id=state.notes_revision_id,
            preferences=NotePreferences(),
            instruction="详细解释",
        ),
        "context-revise",
    )
    asyncio.run(run_operation(study.claim_next(), application.state.settings, repo, ContextModel()))
    completed = study.operation(task.id, revise.id)
    assert completed.status == "succeeded", completed.error
    applied = request(
        application,
        "POST",
        f"/api/tasks/{task.id}/notes-revisions/{completed.output.notes_revision_id}/apply",
        json={"expected_current_id": str(state.notes_revision_id)},
    )
    assert applied.status_code == 200, applied.text
    assert study.state(task.id).quiz_batch_id == state.quiz_batch_id


def test_visual_failure_degrades_to_valid_subtitles(application, monkeypatch):
    task, repo = prepared_context(application)
    # Add video asset at upload time via separate fixture app to exercise branch.
    from sqlalchemy import insert

    from app.db.models import AssetRow
    from app.schemas.tasks import InputAsset

    asset = InputAsset(
        id=uuid4(),
        task_id=task.id,
        kind="video",
        original_name="x.mp4",
        size_bytes=len(MP4),
        storage_key=f"tasks/{task.id}/inputs/video.mp4",
        sha256="a" * 64,
    )
    with repo.engine.begin() as conn:
        conn.execute(
            insert(AssetRow).values(
                id=str(asset.id),
                task_id=str(task.id),
                kind="video",
                payload=asset.model_dump(mode="json"),
            )
        )

    def failed(*args):
        raise StudyError("OCR_UNAVAILABLE", "不可用", 503)

    path = ArtifactStore(application.state.settings.data_dir, None).path(asset.storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MP4)
    monkeypatch.setattr("app.services.transcription.probe_video", lambda *a: 2000)
    # Pin fixture hash to the actual self-created container.
    from sqlalchemy import update

    asset.sha256 = file_hash(path)
    with repo.engine.begin() as conn:
        conn.execute(
            update(AssetRow)
            .where(AssetRow.id == str(asset.id))
            .values(payload=asset.model_dump(mode="json"))
        )
    service = VideoContextService(application.state.settings, repo, frames=failed)
    result = service.store.read_json(service.prepare_video_context(task), VideoContextSnapshot)
    assert result.transcript and result.branch_statuses["ocr"] == "failed"
    assert result.warnings == ["OCR_UNAVAILABLE"]


def test_double_empty_fails_and_invalid_subtitle_is_not_hidden(application, monkeypatch):
    monkeypatch.setattr("app.services.transcription.TranscriptService.extract_audio", no_audio)
    task, repo = prepared_context(application, visual=True)
    service = VideoContextService(
        application.state.settings, repo, frames=lambda *a: [], ocr=FakeOCR()
    )
    with pytest.raises(StudyError, match="CONTEXT_EMPTY"):
        service.prepare_video_context(task)


def test_asr_unavailable_degrades_to_valid_ocr_with_warning(application, monkeypatch):
    task, repo = prepared_context(application, visual=True, notes=False, quiz=False)
    monkeypatch.setattr(
        "app.services.transcription.TranscriptService.extract_audio", lambda *a: None
    )

    def failed(*a):
        raise StudyError("ASR_UNAVAILABLE", "测试缺少 ASR", 503)

    monkeypatch.setattr("app.services.transcription.TranscriptService.transcribe_audio", failed)
    service = VideoContextService(
        application.state.settings, repo, ocr=FakeOCR(), frames=fake_frames
    )
    context = service.store.read_json(service.prepare_video_context(task), VideoContextSnapshot)
    assert context.transcript is None and context.branch_statuses["transcript"] == "failed"
    assert context.branch_statuses["ocr"] == "succeeded" and "ASR_UNAVAILABLE" in context.warnings


def test_nonempty_v2_upgrade_keeps_hashes_foreign_keys_and_no_automatic_upgrade(tmp_path):
    from app.core.config import Settings
    from app.db.repository import TaskRepository, now
    from app.schemas.iteration import NotesRevision, TranscriptSnapshot
    from app.schemas.study import StudyOptions
    from app.schemas.tasks import Task
    from app.services.context_operations import ensure_context_schema

    settings = Settings(_env_file=None, data_dir=tmp_path)
    engine = initialize_database(tmp_path / "app.db", revision="0003_study_foundation")
    repo = TaskRepository(engine)
    task = Task(id=uuid4(), title="旧课程", options=StudyOptions(), created_at=now())
    repo.create(task, [])
    study = StudyRepository(engine)
    source = study.add_snapshot(
        TranscriptSnapshot(
            id=uuid4(),
            task_id=task.id,
            storage_key="legacy/source.json",
            sha256="a" * 64,
            created_at=now(),
        )
    )
    before = study.add_notes(
        NotesRevision(
            id=uuid4(),
            task_id=task.id,
            transcript_snapshot_id=source.id,
            storage_key="legacy/notes.json",
            sha256="b" * 64,
            created_at=now(),
        )
    )
    with pytest.raises(StudyError, match="MIGRATION_REQUIRED"):
        ensure_context_schema(settings, engine)
    engine.dispose()
    upgraded = initialize_database(tmp_path / "app.db", revision="0004_video_context")
    try:
        assert StudyRepository(upgraded).notes(before.task_id, before.id) == before
        with upgraded.connect() as conn:
            assert not conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            assert conn.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        upgraded.dispose()
