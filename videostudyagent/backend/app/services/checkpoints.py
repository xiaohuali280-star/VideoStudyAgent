"""Validated, content-addressed partial notes, separate from published artifacts."""

import json
import os
import tempfile

from app.schemas.study import NotesDocument
from app.services.storage import ArtifactStore, cache_key


class NoteCheckpoints:
    def __init__(self, root):
        self.store = ArtifactStore(root, None)

    def path(self, key):
        return self.store.path(f"cache/note-parts/{key}.json")

    def read(self, key, validate):
        try:
            envelope = json.loads(self.path(key).read_bytes())
            if cache_key(document=envelope["document"]) != envelope["sha256"]:
                return None
            value = NotesDocument.model_validate(envelope["document"])
            validate(value)
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def write(self, key, value):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = value.model_dump(mode="json")
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            stream.write(
                json.dumps({"document": data, "sha256": cache_key(document=data)}).encode()
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
