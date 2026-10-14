from pydantic import TypeAdapter

from app.schemas.iteration import QuizDocumentV11
from app.schemas.study import QuizDocument


class QuizReader:
    @classmethod
    def model_validate_json(cls, data):
        return TypeAdapter(QuizDocument | QuizDocumentV11).validate_json(data)
