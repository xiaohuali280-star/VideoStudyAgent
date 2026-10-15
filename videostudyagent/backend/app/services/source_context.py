from app.adapters.grounding import normalized, quote_present


def source_items(context):
    items = []
    if context.transcript:
        items += [
            dict(
                source_type="transcript",
                source_id=s.id,
                text=s.text,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                frame_id=None,
            )
            for s in context.transcript.segments
        ]
    frames = {f.id: f for f in context.frames}
    items += [
        dict(
            source_type="ocr",
            source_id=o.id,
            text=o.raw_text,
            start_ms=frames[o.frame_id].timestamp_ms,
            end_ms=frames[o.frame_id].timestamp_ms,
            frame_id=str(o.frame_id),
        )
        for o in context.observations
        if o.status == "succeeded" and o.raw_text.strip()
    ]
    return sorted(items, key=lambda s: (s["start_ms"], s["source_type"], s["source_id"]))


def validate_refs(refs, context, allowed=None):
    sources = {(s["source_type"], s["source_id"]): s for s in source_items(context)}
    for ref in refs:
        key = (ref.source_type, ref.source_id)
        if (
            ref.task_id != context.task_id
            or ref.snapshot_id != context.id
            or key not in sources
            or (allowed is not None and key not in allowed)
            or not quote_present(ref.quote, sources[key]["text"])
        ):
            raise ValueError("Invalid context evidence")


def validate_context_document(
    document, context, *, require_coverage=False, previous=(), notes=None
):
    if document.context_snapshot_id != context.id:
        raise ValueError("Context snapshot mismatch")
    sections = document.chapters if hasattr(document, "chapters") else document.questions
    cited = set()
    for section in sections:
        validate_refs(section.source_refs, context)
        transcript_ids = {r.source_id for r in section.source_refs if r.source_type == "transcript"}
        if set(section.source_segment_ids) - transcript_ids:
            raise ValueError("Legacy IDs must agree with typed references")
        cited.update((r.source_type, r.source_id) for r in section.source_refs)
    if require_coverage and cited != {
        (s["source_type"], s["source_id"]) for s in source_items(context)
    }:
        raise ValueError("Notes must cover every canonical source")
    if hasattr(document, "questions"):
        chapter_ids = {c.id for c in notes.chapters} if notes else set()
        if any(
            q.chapter_id is not None and q.chapter_id not in chapter_ids for q in document.questions
        ):
            raise ValueError("Quiz references an unknown chapter")
        questions = [normalized(q.question) for q in document.questions]
        if len(set(questions)) != len(questions) or set(questions) & {
            normalized(q) for q in previous
        }:
            raise ValueError("Duplicate questions")
