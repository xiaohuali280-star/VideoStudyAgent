from pydantic import TypeAdapter

from app.schemas.study import NotesDocument, NotesDocumentV11
from app.schemas.video_context import NotesDocumentV12


class NoteReader:
    adapter = TypeAdapter(NotesDocument | NotesDocumentV11 | NotesDocumentV12)
    model_validate_json = adapter.validate_json
