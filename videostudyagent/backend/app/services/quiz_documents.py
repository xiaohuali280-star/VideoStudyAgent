from pydantic import TypeAdapter

from app.schemas.iteration import QuizDocumentV11
from app.schemas.study import QuizDocument
from app.schemas.video_context import QuizDocumentV12


class QuizReader:
    @classmethod
    def model_validate_json(cls, data):
        return TypeAdapter(QuizDocument | QuizDocumentV11 | QuizDocumentV12).validate_json(data)
