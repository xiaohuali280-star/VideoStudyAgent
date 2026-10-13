from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app import __version__
from app.core.config import Settings
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
    application = FastAPI(
        title="VideoStudyAgent",
        version=__version__,
        description="Stage 1: health and versioned contracts. Study actions are not enabled.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )

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
