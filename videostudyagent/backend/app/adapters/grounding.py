"""D2 adapted from DeepTutor _grounding.py and reading/quiz.py; Apache-2.0.

Changed: per-segment checks; preserve numbers and hyphens; keep evidence in output;
strict short-answer contract with configurable count; no fixed context truncation.
"""

from app.schemas.study import NotesDocument, QuizDocument, StudyOptions, Transcript


def normalized_with_map(value: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    source_positions: list[int] = []
    for index, character in enumerate(value):
        if character.isspace():
            if normalized and normalized[-1] != " ":
                normalized.append(" ")
                source_positions.append(index)
            continue
        normalized.append(character)
        source_positions.append(index)
    if normalized and normalized[-1] == " ":
        normalized.pop()
        source_positions.pop()
    return "".join(normalized), source_positions


def normalized(value: str) -> str:
    return normalized_with_map(value)[0].casefold()


def quote_present(quote: str, source: str) -> bool:
    quote, source = normalized(quote), normalized(source)
    if not quote:
        return False
    offset = 0
    while (index := source.find(quote, offset)) >= 0:
        end = index + len(quote)
        left_cut = quote[0] in "0123456789." and index > 0 and source[index - 1] in "+-−.0123456789"
        right_cut = (
            quote[-1] in "0123456789." and end < len(source) and source[end] in ".0123456789"
        )
        if not left_cut and not right_cut:
            return True
        offset = index + 1
    return False


def validate_notes(notes: NotesDocument, transcript: Transcript, allowed_ids=None):
    allowed = set(allowed_ids or [segment.id for segment in transcript.segments])
    referred = {ref for chapter in notes.chapters for ref in chapter.source_segment_ids}
    if referred != allowed:
        raise ValueError("Note chapters must cover exactly the supplied source IDs")


def validate_quiz(
    quiz: QuizDocument, transcript: Transcript, notes: NotesDocument, options: StudyOptions
):
    if quiz.question_count != options.question_count or quiz.difficulty != options.difficulty:
        raise ValueError("Quiz must match the immutable options")
    sources = {segment.id: segment.text for segment in transcript.segments}
    chapters = {chapter.id: chapter for chapter in notes.chapters}
    prompts = []
    for question in quiz.questions:
        if question.chapter_id not in chapters:
            raise ValueError("Unknown chapter")
        if not set(question.source_segment_ids) & set(
            chapters[question.chapter_id].source_segment_ids
        ):
            raise ValueError("Question must refer to its chapter")
        for evidence in question.evidence:
            if evidence.segment_id not in sources or not quote_present(
                evidence.quote, sources[evidence.segment_id]
            ):
                raise ValueError("Evidence must appear in its original segment")
        prompts.append(normalized(question.question))
    if len(set(prompts)) != len(prompts):
        raise ValueError("Duplicate questions")
