import asyncio

from app.db.study_repository import StudyRepository
from app.services.operations import run_operation
from tests.scripted_llm import ScriptedStudyModel
from tests.test_config_health import request
from tests.test_upload_persistence import upload


def test_preferences_draft_apply_restore_discard_and_stale_base(application):
    task_id = upload(application).json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    model = ScriptedStudyModel()
    asyncio.run(run_operation(study.claim_next(), application.state.settings, repo, model))
    before = study.state(task_id)
    original = request(application, "GET", f"/api/tasks/{task_id}/result").json()
    prefs = {"detail": "concise", "style": "review", "include_examples": True}
    pref_url = f"/api/tasks/{task_id}/note-preferences"
    assert (
        request(
            application, "PUT", pref_url, json={"expected_revision": 0, "preferences": prefs}
        ).status_code
        == 200
    )
    assert (
        request(
            application, "PUT", pref_url, json={"expected_revision": 0, "preferences": prefs}
        ).status_code
        == 409
    )
    assert study.state(task_id) == before
    action = {
        "kind": "revise_notes",
        "transcript_snapshot_id": str(before.transcript_snapshot_id),
        "base_revision_id": str(before.notes_revision_id),
        "preferences": prefs,
        "instruction": "用简洁提纲保留事实",
        "chapter_ids": [],
    }

    def draft(key):
        response = request(
            application,
            "POST",
            f"/api/tasks/{task_id}/operations",
            json=action,
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 202, response.text
        op = study.claim_next()
        asyncio.run(run_operation(op, application.state.settings, repo, model))
        result = study.operation(task_id, op.id)
        assert result.status == "succeeded", result.error
        return result.output.notes_revision_id

    first, second = draft("first"), draft("second")
    assert study.state(task_id) == before

    def apply(version, current):
        return request(
            application,
            "POST",
            f"/api/tasks/{task_id}/notes-revisions/{version}/apply",
            json={"expected_current_id": str(current)},
        )

    assert apply(first, before.notes_revision_id).status_code == 200
    now = request(application, "GET", f"/api/tasks/{task_id}/result")
    assert now.status_code == 200 and now.json()["notes"]["schema_version"] == "1.1"
    assert now.json()["quiz"] == original["quiz"]
    assert apply(second, first).status_code == 409
    assert (
        request(
            application, "POST", f"/api/tasks/{task_id}/notes-revisions/{second}/discard"
        ).status_code
        == 200
    )
    assert apply(second, first).status_code == 409
    assert apply(before.notes_revision_id, first).status_code == 200
    assert (
        request(application, "GET", f"/api/tasks/{task_id}/result").json()["notes"]
        == original["notes"]
    )
    assert (
        request(
            application, "GET", f"/api/tasks/{task_id}/exports/notes.md?notes_revision_id={first}"
        ).status_code
        == 200
    )
