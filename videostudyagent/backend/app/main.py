from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app import __version__
from app.api import router
from app.core.config import Settings
from app.core.errors import StudyError
from app.schemas.common import ErrorInfo, ErrorResponse, HealthResponse
from app.schemas.providers import ModelReply, ModelRequest, ToolCall, ToolDefinition
from app.schemas.study import NotesDocument, QuizDocument, StudyOptions, Transcript, TranscriptChunk
from app.schemas.tasks import (
    Artifact,
    CacheEntry,
    InputAsset,
    StudyResult,
    Task,
    TaskDetail,
    TaskStep,
    ToolCallRecord,
)

DOMAIN_CONTRACTS = (
    StudyOptions,
    Transcript,
    TranscriptChunk,
    NotesDocument,
    QuizDocument,
    Task,
    TaskDetail,
    TaskStep,
    StudyResult,
    InputAsset,
    Artifact,
    CacheEntry,
    ToolCallRecord,
    ModelRequest,
    ModelReply,
    ToolCall,
    ToolDefinition,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app):
        yield
        if hasattr(app.state, "repository"):
            app.state.repository.engine.dispose()

    application = FastAPI(
        title="VideoStudyAgent",
        version=__version__,
        description="Local course study API. Upload and task persistence are available.",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.include_router(router)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @application.middleware("http")
    async def limit_request_body(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/api/tasks":
            limit = settings.max_video_bytes + settings.max_subtitle_bytes + 65536
            received = 0
            original = request.receive

            async def limited_receive():
                nonlocal received
                message = await original()
                received += len(message.get("body", b""))
                if received > limit:
                    raise StudyError("UPLOAD_TOO_LARGE", "上传内容超过大小限制。", 413)
                return message

            request._receive = limited_receive
        return await call_next(request)

    @application.exception_handler(StudyError)
    async def study_error(_: Request, exc: StudyError) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorInfo(
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                step=exc.step,
            )
        )
        return JSONResponse(status_code=exc.status, content=payload.model_dump(mode="json"))

    @application.get(
        "/api/health",
        response_model=HealthResponse,
        responses={500: {"model": ErrorResponse}},
    )
    def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    @application.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return error_response(422, "VALIDATION_ERROR", "请求参数不符合接口约定。")

    @application.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return error_response(404, "NOT_FOUND", "未找到请求的资源。")
        return error_response(exc.status_code, "HTTP_ERROR", "请求无法完成。")

    @application.exception_handler(Exception)
    async def unexpected_error(_: Request, __: Exception) -> JSONResponse:
        return error_response(500, "INTERNAL_ERROR", "服务暂时无法完成请求。")

    def openapi() -> dict:
        if application.openapi_schema is None:
            schema = get_openapi(
                title=application.title,
                version=application.version,
                description=application.description,
                routes=application.routes,
            )
            components = schema.setdefault("components", {}).setdefault("schemas", {})
            # Publish future DTOs without advertising unimplemented HTTP routes.
            for model in DOMAIN_CONTRACTS:
                model_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
                components.update(model_schema.pop("$defs", {}))
                components[model.__name__] = model_schema
            application.openapi_schema = schema
        return application.openapi_schema

    application.openapi = openapi
    return application


def error_response(status: int, code: str, message: str) -> JSONResponse:
    payload = ErrorResponse(error=ErrorInfo(code=code, message=message))
    return JSONResponse(status_code=status, content=payload.model_dump(mode="json"))


app = create_app()
