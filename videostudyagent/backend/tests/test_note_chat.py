import asyncio

from app.db.study_repository import StudyRepository
from app.services.operations import run_operation
from tests.scripted_llm import ScriptedStudyModel
from tests.test_config_health import request
from tests.test_upload_persistence import upload


def test_chat_persistent_scoped_grounded_idempotent_and_read_only(application):
    task_id = upload(application).json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    asyncio.run(
        run_operation(study.claim_next(), application.state.settings, repo, ScriptedStudyModel())
    )
    before = study.state(task_id)
    conversation = request(application, "POST", f"/api/tasks/{task_id}/conversations").json()["id"]
    notes = request(application, "GET", f"/api/tasks/{task_id}/result").json()["notes"]
    body = {
        "kind": "chat_reply",
        "conversation_id": conversation,
        "notes_revision_id": str(before.notes_revision_id),
        "chapter_ids": [notes["chapters"][0]["id"]],
        "message": "分析所选章节",
    }
    url = f"/api/tasks/{task_id}/operations"

    def send():
        return request(application, "POST", url, json=body, headers={"Idempotency-Key": "chat1"})

    first, second = send(), send()
    assert first.status_code == 202 and first.json()["id"] == second.json()["id"]
    asyncio.run(
        run_operation(study.claim_next(), application.state.settings, repo, ScriptedStudyModel())
    )
    assert study.operation(task_id, first.json()["id"]).status == "succeeded"
    messages = request(
        application, "GET", f"/api/tasks/{task_id}/conversations/{conversation}/messages"
    ).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["citations"]
    assert study.state(task_id) == before
    body["chapter_ids"] = ["made_up"]
    assert send().status_code == 422
    other = upload(application).json()["id"]
    assert (
        request(
            application, "GET", f"/api/tasks/{other}/conversations/{conversation}/messages"
        ).status_code
        == 404
    )
