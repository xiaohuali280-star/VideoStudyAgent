"""Publication review and one bounded repair; no additional Agent loop."""

from app.adapters.grounding import validate_notes
from app.schemas.study import NotesDocument, QuestionV11
from app.schemas.video_context import NotesDocumentV12, QuestionV12
from app.services.context_generation import SYSTEM
from app.services.review import ReviewService, SourceScopeResolver


async def review_candidate(operation, document, source, snapshot_id, generation, validate):
    scope = SourceScopeResolver(operation.task_id, snapshot_id, source)

    async def repair(candidate, report, scope):
        targets = {i.target_id for i in report.issues}
        changes = {}
        is_notes = hasattr(candidate, "chapters")
        sections = candidate.chapters if is_notes else candidate.questions
        for section in sections:
            if section.id not in targets:
                continue
            ids = (
                [r.source_id for r in section.source_refs]
                if hasattr(section, "source_refs")
                else section.source_segment_ids
            )
            evidence = scope.resolve(
                set(ids) | set(report.required_source_ids), report.required_time_ranges
            )
            data = dict(
                task_id=str(scope.task_id),
                snapshot_id=str(scope.snapshot_id),
                title=getattr(candidate, "title", "课程"),
                original=section.model_dump(mode="json"),
                issues=[
                    i.model_dump(mode="json") for i in report.issues if i.target_id == section.id
                ],
                source_items=evidence,
                segments=[dict(segment_id=s["source_id"], text=s["text"]) for s in evidence],
            )
            if is_notes:
                schema = (
                    NotesDocumentV12 if hasattr(candidate, "context_snapshot_id") else NotesDocument
                )

                def valid(value):
                    if schema is NotesDocument:
                        validate_notes(value, source, ids)
                    else:
                        from app.services.source_context import validate_context_document

                        validate_context_document(value, source)
                        if {
                            (r.source_type, r.source_id)
                            for c in value.chapters
                            for r in c.source_refs
                        } != {(r.source_type, r.source_id) for r in section.source_refs}:
                            raise ValueError("Repair changed source scope")

                value = await generation._structured(
                    SYSTEM + "只修复原章节，保留来源。", data, schema, valid
                )
                changes[section.id] = section.model_copy(
                    update={
                        "title": value.chapters[0].title,
                        "content_markdown": "\n\n".join(c.content_markdown for c in value.chapters),
                    }
                )
            else:
                schema = QuestionV12 if hasattr(section, "source_refs") else QuestionV11

                def valid(value):
                    trial = candidate.model_copy(
                        update={
                            "questions": [
                                value.model_copy(update={"id": section.id})
                                if q.id == section.id
                                else q
                                for q in candidate.questions
                            ]
                        }
                    )
                    validate(trial)

                value = await generation._structured(
                    SYSTEM + "只修复原题，保持其他题目不变。", data, schema, valid
                )
                changes[section.id] = value.model_copy(update={"id": section.id})
        return candidate.model_copy(
            update={
                "chapters" if is_notes else "questions": [changes.get(s.id, s) for s in sections]
            }
        )

    updated, report = await ReviewService(generation.repository, generation).gate(
        operation, document, scope, validate, repair
    )
    return updated, dict(review_policy=report.policy, review_report_id=report.id)
