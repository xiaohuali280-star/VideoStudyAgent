from pydantic import TypeAdapter

from app.schemas.study import NotesDocument, NotesDocumentV11


class NoteReader:
    adapter = TypeAdapter(NotesDocument | NotesDocumentV11)
    model_validate_json = adapter.validate_json
