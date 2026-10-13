import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.study import StudyOptions


def request(application, method, path, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_health_needs_no_key_models_or_database(tmp_path):
    data_dir = tmp_path / "not-created"
    application = create_app(Settings(_env_file=None, data_dir=data_dir))
    response = request(application, "GET", "/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "status": "ok",
        "service": "VideoStudyAgent",
        "version": "0.1.0",
        "stage": 2,
    }
    assert request(application, "GET", "/api/not-implemented").status_code == 404
    assert not data_dir.exists()


def test_local_env_loading_and_secret_redaction(tmp_path):
    synthetic_secret = "test-only-" + uuid4().hex
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"VSA_LLM_API_KEY={synthetic_secret}\nVSA_MAX_VIDEO_BYTES=100\n", encoding="utf-8"
    )
    settings = Settings(_env_file=env_file)
    assert settings.llm_api_key.get_secret_value() == synthetic_secret
    assert settings.max_video_bytes == 100
    assert synthetic_secret not in repr(settings)
    assert "llm_api_key" not in settings.model_dump()
    application = create_app(settings)
    for path in ("/api/health", "/openapi.json", "/unknown"):
        assert synthetic_secret not in request(application, "GET", path).text


def test_environment_overrides_local_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("VSA_MAX_VIDEO_BYTES=100\n", encoding="utf-8")
    monkeypatch.setenv("VSA_MAX_VIDEO_BYTES", "200")
    assert Settings(_env_file=env_file).max_video_bytes == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_video_bytes": 0},
        {"max_subtitle_bytes": -1},
        {"max_duration_ms": 0},
        {"asr_device": "tpu"},
        {"llm_base_url": "https://user:password@example.invalid"},
    ],
)
def test_invalid_settings_are_rejected(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_cors_is_limited_to_configured_local_origins():
    application = create_app(Settings(_env_file=None))
    allowed = request(
        application,
        "OPTIONS",
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    rejected = request(
        application,
        "OPTIONS",
        "/api/health",
        headers={
            "Origin": "https://example.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "access-control-allow-origin" not in rejected.headers


def test_openapi_snapshot_and_all_component_references():
    schema = create_app(Settings(_env_file=None)).openapi()
    assert set(schema["paths"]) == {
        "/api/health",
        "/api/tasks",
        "/api/tasks/{task_id}",
        "/api/tasks/{task_id}/retry",
    }
    assert "QuizDocument" in schema["components"]["schemas"]
    snapshot = json.loads((Path(__file__).parents[1] / "openapi.json").read_text("utf-8"))
    assert schema == snapshot

    def check(value):
        if isinstance(value, dict):
            if "$ref" in value:
                target = value["$ref"].split("/")[-1]
                assert target in schema["components"]["schemas"]
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(schema)


def test_errors_do_not_echo_raw_exception_or_client_text():
    application = create_app(Settings(_env_file=None))

    @application.get("/test-failure")
    def fail():
        raise RuntimeError("private-error-detail")

    response = request(application, "GET", "/test-failure")
    missing = request(application, "GET", "/private-client-input")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private-error-detail" not in response.text
    assert "private-client-input" not in missing.text


def test_validation_errors_are_sanitized():
    application = create_app(Settings(_env_file=None))

    @application.post("/test-validation")
    def validate(options: StudyOptions):
        return options

    response = request(
        application, "POST", "/test-validation", json={"difficulty": "private-invalid-value"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "private-invalid-value" not in response.text
