from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.db.context_repository import VideoContextRepository
from app.db.study_repository import StudyRepository
from app.services.review import SourceScopeResolver
from app.services.study_versions import VersionReader


def read_source(repository, root, task_id, snapshot_id, snapshot_type, notes_revision_id=None):
    study = StudyRepository(repository.engine)
    if snapshot_type == "context":
        source = VideoContextRepository(repository.engine).get(task_id, snapshot_id)
        digest = source.manifest_sha256
    else:
        snapshot = study.snapshot(task_id, snapshot_id)
        source = VersionReader(root).transcript(snapshot)
        digest = snapshot.sha256
    if notes_revision_id:
        from app.core.errors import StudyError

        notes = study.notes(task_id, notes_revision_id)
        expected = (
            notes.context_snapshot_id
            if snapshot_type == "context"
            else notes.transcript_snapshot_id
        )
        if expected != snapshot_id or (snapshot_type == "transcript" and notes.context_snapshot_id):
            raise StudyError("STUDY_CONFLICT", "检索快照与所选笔记来源不匹配。", 409)
    return SourceScopeResolver(task_id, snapshot_id, source), digest


def index_source(repository, root, task_id, snapshot_id, snapshot_type):
    try:
        return _index_source(repository, root, task_id, snapshot_id, snapshot_type)
    except OperationalError:
        return False  # Derived index failure never invalidates authoritative sources.


def _index_source(repository, root, task_id, snapshot_id, snapshot_type):
    if "evidence_documents" not in inspect(repository.engine).get_table_names():
        return False
    scope, digest = read_source(repository, root, task_id, snapshot_id, snapshot_type)
    parameters = dict(task=str(task_id), snapshot=str(snapshot_id), kind=snapshot_type)
    with repository.engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        generation = (
            connection.scalar(
                text(
                    "SELECT generation FROM evidence_index_manifests "
                    "WHERE task_id=:task AND snapshot_id=:snapshot AND snapshot_type=:kind"
                ),
                parameters,
            )
            or 0
        )
        fts = connection.scalar(text("SELECT 1 FROM sqlite_master WHERE name='evidence_fts'"))
        if fts:
            connection.execute(
                text(
                    "DELETE FROM evidence_fts WHERE rowid IN "
                    "(SELECT id FROM evidence_documents WHERE task_id=:task "
                    "AND snapshot_id=:snapshot "
                    "AND snapshot_type=:kind)"
                ),
                parameters,
            )
        connection.execute(
            text(
                "DELETE FROM evidence_documents WHERE task_id=:task "
                "AND snapshot_id=:snapshot AND snapshot_type=:kind"
            ),
            parameters,
        )
        for item in scope.items:
            result = connection.execute(
                text(
                    "INSERT INTO evidence_documents(task_id,snapshot_id,"
                    "snapshot_type,source_type,source_id,start_ms,end_ms,raw_text,frame_id) "
                    "VALUES (:task,:snapshot,:kind,:source_type,:source_id,"
                    ":start_ms,:end_ms,:raw_text,:frame_id)"
                ),
                parameters
                | dict(
                    source_type=item["source_type"],
                    source_id=item["source_id"],
                    start_ms=item["start_ms"],
                    end_ms=item["end_ms"],
                    raw_text=item["text"],
                    frame_id=item.get("frame_id"),
                ),
            )
            if fts:
                connection.execute(
                    text("INSERT INTO evidence_fts(rowid,raw_text) VALUES (:id,:text)"),
                    dict(id=result.lastrowid, text=item["text"]),
                )
        connection.execute(
            text(
                "INSERT INTO evidence_index_manifests(task_id,snapshot_id,"
                "snapshot_type,source_sha256,tokenizer_version,generation,state) "
                "VALUES (:task,:snapshot,:kind,:sha,'trigram-v1',:generation,'ready') "
                "ON CONFLICT(task_id,snapshot_id,snapshot_type) DO UPDATE SET "
                "source_sha256=excluded.source_sha256,tokenizer_version=excluded.tokenizer_version,"
                "generation=excluded.generation,state=excluded.state"
            ),
            parameters | dict(sha=digest, generation=generation + 1),
        )
    return True
