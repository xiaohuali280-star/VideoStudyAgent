import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.errors import StudyError
from app.db.repository import TaskRepository, initialize_database, now
from app.db.session import create_database_engine
from app.db.study_repository import StudyRepository
from app.schemas.iteration import ChatReplyRequest, NotesRevision, TranscriptSnapshot
from app.schemas.retrieval import EvidenceQuery
from app.schemas.study import StudyOptions, Transcript, TranscriptSegment
from app.schemas.tasks import Task
from app.services.indexing import index_source
from app.services.operations import VersionWriter, run_operation
from app.services.retrieval import retrieve
from tests.scripted_llm import ScriptedStudyModel
from tests.test_upload_persistence import upload


def seed(application, items=None, repository=None, task=None):
    settings = application.state.settings
    if repository is None:
        engine = initialize_database(settings.data_dir / "app.db", revision="0006_evidence_index")
        repository = TaskRepository(engine)
        application.state.repository = repository
    if task is None:
        task = Task(
            id=uuid4(),
            title="自建检索课程",
            options=StudyOptions(generate_notes=False, generate_quiz=False),
            created_at=now(),
        )
        repository.create(task, [])
    items = items or [
        "梯度下降使用学习率 -0.1。",
        "学习率 controls step size。",
        "Python attention_mask 屏蔽填充位。",
        "矩阵乘法不同于逐元素乘法。",
    ]
    transcript = Transcript(
        source="subtitle",
        language="zh-CN",
        duration_ms=len(items) * 1000,
        segments=[
            TranscriptSegment(id=f"s{i:03d}", start_ms=i * 1000, end_ms=(i + 1) * 1000, text=value)
            for i, value in enumerate(items)
        ],
    )
    snapshot = StudyRepository(repository.engine).add_snapshot(
        TranscriptSnapshot(
            id=uuid4(),
            task_id=task.id,
            created_at=now(),
            **VersionWriter(settings.data_dir).write(task.id, "transcript", transcript),
        )
    )
    assert index_source(repository, settings.data_dir, task.id, snapshot.id, "transcript")
    return repository, task, snapshot


def query(snapshot, value, **kwargs):
    return EvidenceQuery(snapshot_id=snapshot.id, snapshot_type="transcript", query=value, **kwargs)


def test_frozen_lexical_gold_recall_mrr_short_chinese_and_empty(application, tmp_path):
    repo, task, snapshot = seed(application)
    gold = json.loads(
        (Path(__file__).parents[1] / "evaluation/cases/retrieval-v1.json").read_text("utf-8")
    )
    recalls, reciprocals = [], []
    for case in gold:
        result = retrieve(
            repo, application.state.settings.data_dir, task.id, query(snapshot, case["query"])
        )
        ids = [h.source_id for h in result.hits]
        relevant = set(case["relevant"])
        if relevant:
            recalls.append(len(relevant & set(ids)) / len(relevant))
            reciprocals.append(
                next((1 / (i + 1) for i, item in enumerate(ids) if item in relevant), 0)
            )
        else:
            assert ids == []
        assert result.mode == "lexical_fts5" and not result.warnings
    report = dict(
        recall_at_5=sum(recalls) / len(recalls),
        mrr=sum(reciprocals) / len(reciprocals),
        scope="self_created_lexical_fixture",
        semantic_quality="not_verified",
    )
    assert report["recall_at_5"] == 1 and report["mrr"] >= 0.9
    (tmp_path / "retrieval-metrics.json").write_text(json.dumps(report))


def test_course_snapshot_filters_before_topk_and_old_note_binding(application):
    repo, task, old = seed(application)
    _, other, _ = seed(application, ["attention_mask secret other course"] * 30, repo)
    new = seed(application, ["new snapshot unrelated"], repo, task)[2]
    result = retrieve(
        repo, application.state.settings.data_dir, task.id, query(old, "attention_mask", top_k=1)
    )
    assert len(result.hits) == 1 and result.hits[0].task_id == task.id
    assert result.hits[0].snapshot_id == old.id and "secret" not in result.hits[0].raw_text
    assert (
        retrieve(
            repo,
            application.state.settings.data_dir,
            task.id,
            query(old, "attention_mask", end_ms=1999),
        ).hits
        == []
    )
    note = StudyRepository(repo.engine).add_notes(
        NotesRevision(
            id=uuid4(),
            task_id=task.id,
            transcript_snapshot_id=old.id,
            storage_key="test/notes.json",
            sha256="a" * 64,
            created_at=now(),
        )
    )
    with pytest.raises(StudyError, match="STUDY_CONFLICT"):
        retrieve(
            repo,
            application.state.settings.data_dir,
            task.id,
            query(new, "attention_mask", notes_revision_id=note.id),
        )
    with pytest.raises(StudyError, match="NOT_FOUND"):
        retrieve(repo, application.state.settings.data_dir, other.id, query(old, "attention_mask"))


@pytest.mark.parametrize("damage", ["document", "fts", "manifest"])
def test_corrupt_missing_index_falls_back_and_rebuilds(application, damage):
    repo, task, snapshot = seed(application)
    with repo.engine.begin() as conn:
        if damage == "fts":
            conn.exec_driver_sql("DROP TABLE evidence_fts")
        elif damage == "document":
            conn.execute(text("UPDATE evidence_documents SET raw_text='corrupted derivative'"))
        else:
            conn.execute(text("UPDATE evidence_index_manifests SET source_sha256='invalid'"))
    result = retrieve(repo, application.state.settings.data_dir, task.id, query(snapshot, "梯度"))
    assert result.hits and result.mode == "scoped_source_fallback" and result.warnings
    assert "梯度" in result.hits[0].raw_text and "corrupted" not in result.hits[0].raw_text
    assert index_source(
        repo, application.state.settings.data_dir, task.id, snapshot.id, "transcript"
    )
    if damage != "fts":
        assert (
            retrieve(
                repo, application.state.settings.data_dir, task.id, query(snapshot, "梯度")
            ).mode
            == "lexical_fts5"
        )


def test_malicious_match_is_literal_and_restart_no_hidden_generation(application):
    repo, task, snapshot = seed(application)
    result = retrieve(
        repo,
        application.state.settings.data_dir,
        task.id,
        query(snapshot, '" OR raw_text:*; DROP TABLE tasks --'),
    )
    assert all(h.task_id == task.id for h in result.hits)
    restarted = create_database_engine(application.state.settings.data_dir / "app.db")
    try:
        assert (
            retrieve(
                TaskRepository(restarted),
                application.state.settings.data_dir,
                task.id,
                query(snapshot, "attention_mask"),
            )
            .hits[0]
            .source_id
            == "s002"
        )
        assert StudyRepository(restarted).note_revisions(task.id) == []
    finally:
        restarted.dispose()


def test_bounded_fallback_reports_incomplete_scan(application, monkeypatch):
    repo, task, snapshot = seed(application)
    monkeypatch.setattr("app.services.retrieval.SCAN_LIMIT", 2)
    with repo.engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE evidence_fts")
    result = retrieve(
        repo, application.state.settings.data_dir, task.id, query(snapshot, "矩阵乘法")
    )
    assert not result.hits and result.scanned_sources == 2 and result.total_sources == 4
    assert "RETRIEVAL_SCAN_LIMIT" in result.warnings


def test_ocr_evidence_keeps_point_time_and_source_filter(application, monkeypatch):
    from app.schemas.video_context import VideoContextSnapshot
    from app.services.video_context import VideoContextService
    from tests.test_video_context import FakeOCR, fake_frames, no_audio, prepared_context

    monkeypatch.setattr("app.services.transcription.TranscriptService.extract_audio", no_audio)
    task, repo = prepared_context(application, visual=True, notes=False, quiz=False)
    service = VideoContextService(
        application.state.settings, repo, ocr=FakeOCR(), frames=fake_frames
    )
    context = service.store.read_json(service.prepare_video_context(task), VideoContextSnapshot)
    assert index_source(repo, application.state.settings.data_dir, task.id, context.id, "context")
    search = EvidenceQuery(
        snapshot_id=context.id, snapshot_type="context", query="rate", source_types=["ocr"]
    )
    result = retrieve(repo, application.state.settings.data_dir, task.id, search)
    assert result.hits[0].start_ms == result.hits[0].end_ms == 1234
    assert result.hits[0].frame_id and result.hits[0].source_type == "ocr"
    assert not retrieve(
        repo,
        application.state.settings.data_dir,
        task.id,
        search.model_copy(update={"source_types": ["transcript"]}),
    ).hits


def test_cross_chapter_chat_and_unanswerable_skip_model(application):
    task_id = upload(application).json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    asyncio.run(
        run_operation(study.claim_next(), application.state.settings, repo, ScriptedStudyModel())
    )
    state = study.state(task_id)
    conversation = study.create_conversation(task_id)
    for i, message in enumerate(["Learning rate", "课程完全不存在的术语abcdef"]):
        operation = study.enqueue(
            task_id,
            ChatReplyRequest(
                conversation_id=conversation.id,
                notes_revision_id=state.notes_revision_id,
                chapter_ids=["ch_00001"],
                message=message,
                scope="course_retrieval",
            ),
            f"search-chat-{i}",
        )
        # Use the actual immutable chapter ID.
        from app.services.study_versions import VersionReader

        notes = VersionReader(application.state.settings.data_dir).notes(
            study.notes(task_id, state.notes_revision_id)
        )
        # Request chapter ownership is checked by API/handler; create matching request above below.
        assert notes.chapters
        model = ScriptedStudyModel()
        asyncio.run(run_operation(study.claim_next(), application.state.settings, repo, model))
        assert study.operation(task_id, operation.id).status == "succeeded"
        assert bool(model.requests) == (i == 0)
