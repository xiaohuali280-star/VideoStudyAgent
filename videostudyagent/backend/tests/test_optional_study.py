import asyncio
import json

import pytest

from app.db.study_repository import StudyRepository
from app.services.operations import run_operation
from tests.scripted_llm import ScriptedStudyModel
from tests.test_config_health import request
from tests.test_upload_persistence import upload


@pytest.mark.parametrize("notes,quiz", [(False, False), (True, False), (False, True), (True, True)])
def test_optional_pipeline_publishes_only_requested_results(application, notes, quiz):
    response = upload(
        application, data={"options": json.dumps({"generate_notes": notes, "generate_quiz": quiz})}
    )
    assert response.status_code == 202
    task_id = response.json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    operation = study.claim_next()
    model = ScriptedStudyModel()
    asyncio.run(
        run_operation(operation, application.state.settings, repo, model if notes or quiz else None)
    )
    finished = study.operation(task_id, operation.id)
    assert finished.status == "succeeded", finished.error
    result = request(application, "GET", f"/api/tasks/{task_id}/result")
    assert result.status_code == 200
    assert bool(result.json()["notes"]) == notes
    assert bool(result.json()["quiz"]) == quiz
    if quiz:
        assert len(result.json()["quiz"]["questions"]) == 5
    if not notes and not quiz:
        assert not model.requests
    assert (study.state(task_id).notes_revision_id is not None) == notes
