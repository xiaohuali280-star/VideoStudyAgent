from uuid import uuid4

from app.db.repository import now
from app.db.study_repository import StudyRepository
from app.schemas.iteration import NotesRevision, OperationOutput
from app.schemas.video_context import NotesDocumentV12
from app.services.context_generation import SYSTEM, ContextGenerationService
from app.services.note_revisions import revision_context
from app.services.operations import VersionWriter
from app.services.source_context import source_items, validate_context_document
from app.services.study_versions import VersionReader


async def revise_context_notes(operation, settings, repository, bounded):
    repo, request = StudyRepository(repository.engine), operation.request
    base, notes, context, ids = revision_context(
        repo, VersionReader(settings.data_dir), operation.task_id, request
    )
    service = ContextGenerationService(settings, repository, bounded)
    task, replacements = repository.get(operation.task_id), {}
    for chapter in notes.chapters:
        if chapter.id not in ids:
            continue
        allowed = {(r.source_type, r.source_id) for r in chapter.source_refs}
        sources = [
            s for s in source_items(context) if (s["source_type"], s["source_id"]) in allowed
        ]
        data = service.data(task, context, sources) | dict(
            original_chapter=chapter.model_dump(mode="json"),
            instruction=request.instruction,
            preferences=request.preferences.model_dump(mode="json"),
        )

        def validate(value):
            validate_context_document(value, context)
            if {
                (r.source_type, r.source_id) for c in value.chapters for r in c.source_refs
            } != allowed:
                raise ValueError("Revision must preserve scoped sources")

        result = await service._structured(SYSTEM, data, NotesDocumentV12, validate)
        replacements[chapter.id] = chapter.model_copy(
            update={
                "title": result.chapters[0].title,
                "content_markdown": "\n\n".join(c.content_markdown for c in result.chapters),
            }
        )
    document = notes.model_copy(
        update={"chapters": [replacements.get(c.id, c) for c in notes.chapters]}
    )
    validate_context_document(document, context, require_coverage=True)
    from app.services.review_runtime import review_candidate

    document, approval = await review_candidate(
        operation,
        document,
        context,
        context.id,
        service,
        lambda d: validate_context_document(d, context, require_coverage=True),
    )
    record = repo.add_notes(
        NotesRevision(
            id=uuid4(),
            task_id=operation.task_id,
            context_snapshot_id=context.id,
            transcript_snapshot_id=context.transcript_snapshot_id,
            parent_revision_id=base.id,
            operation_id=operation.id,
            document_schema_version="1.2",
            **approval,
            preferences=request.preferences,
            created_at=now(),
            **VersionWriter(settings.data_dir).write(operation.task_id, "notes", document),
        )
    )
    repo.finish(
        operation.task_id, operation.id, output=OperationOutput(notes_revision_id=record.id)
    )
