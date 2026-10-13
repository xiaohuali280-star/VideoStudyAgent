"""Deterministic test-only JSON replies. Never exposed as an application provider."""

import json

from app.schemas.providers import ModelReply


class ScriptedStudyModel:
    def __init__(self):
        self.requests = []
        self.question_index = 0

    async def complete(self, request):
        self.requests.append(request)
        payload = json.loads(request.messages[1].content)
        data = payload["course_data"]
        if payload["schema"]["title"] == "NotesDocument":
            result = {
                "title": data["title"],
                "learning_objectives": ["Understand the supplied concepts"],
                "chapters": [
                    {
                        "id": "section",
                        "title": "Course concepts",
                        "content_markdown": "\n\n".join(s["text"] for s in data["segments"]),
                        "source_segment_ids": list(
                            dict.fromkeys(s["segment_id"] for s in data["segments"])
                        ),
                    }
                ],
                "key_concepts": ["Learning"],
                "summary": "Review the supplied course concepts.",
            }
        else:
            questions = []
            for _ in range(data["options"]["question_count"]):
                self.question_index += 1
                segment = data["segments"][0]
                question = {
                    "id": f"q_{self.question_index}",
                    "type": "short_answer",
                    "difficulty": data["options"]["difficulty"],
                    "chapter_id": data["chapters"][0]["id"],
                    "question": f"Review concept {self.question_index}: what does the source say?",
                    "answer": segment["text"][:80],
                    "explanation": "The quoted source supports it.",
                    "source_segment_ids": [segment["segment_id"]],
                    "evidence": [
                        {"segment_id": segment["segment_id"], "quote": segment["text"][:80]}
                    ],
                }
                questions.append(question)
            result = {
                "question_count": len(questions),
                "difficulty": data["options"]["difficulty"],
                "questions": questions,
            }
        return ModelReply(content=json.dumps(result, ensure_ascii=False))
