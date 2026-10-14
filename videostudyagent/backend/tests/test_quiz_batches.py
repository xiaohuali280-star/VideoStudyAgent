import asyncio
import json

from app.db.study_repository import StudyRepository
from app.services.operations import run_operation
from tests.scripted_llm import ScriptedStudyModel
from tests.test_config_health import request
from tests.test_upload_persistence import upload


def test_regenerate_idempotent_fresh_history_export_and_failure_keeps_old(application):
    task_id = upload(application).json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    model = ScriptedStudyModel()

    def execute(client=model):
        asyncio.run(run_operation(study.claim_next(), application.state.settings, repo, client))

    execute()
    first = study.quiz_batches(task_id)[0]
    state = study.state(task_id)
    body = {
        "kind": "generate_quiz",
        "transcript_snapshot_id": str(state.transcript_snapshot_id),
        "notes_revision_id": str(state.notes_revision_id),
    }
    url = f"/api/tasks/{task_id}/operations"

    def enqueue(key):
        return request(application, "POST", url, json=body, headers={"Idempotency-Key": key})

    a, b = enqueue("new-batch"), enqueue("new-batch")
    assert a.status_code == 202 and a.json()["id"] == b.json()["id"]
    execute()
    batches = request(application, "GET", f"/api/tasks/{task_id}/quiz-batches").json()
    assert len(batches) == 2
    old = request(
        application, "GET", f"/api/tasks/{task_id}/exports/quiz.json?quiz_batch_id={first.id}"
    )
    assert old.status_code == 200
    current = request(application, "GET", f"/api/tasks/{task_id}/result").json()["quiz"]
    assert {q["question"] for q in old.json()["questions"]}.isdisjoint(
        {q["question"] for q in current["questions"]}
    )
    before = study.state(task_id).quiz_batch_id
    enqueue("duplicate")
    execute(ScriptedStudyModel())  # repeated text fails bounded validation
    assert study.state(task_id).quiz_batch_id == before
    assert study.operations(task_id)[0].status == "failed"
    other = upload(
        application, data={"options": json.dumps({"generate_notes": False, "generate_quiz": False})}
    ).json()["id"]
    assert (
        request(application, "GET", f"/api/tasks/{other}/quiz-batches/{first.id}").status_code
        == 404
    )
