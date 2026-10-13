from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from app.schemas.common import ErrorInfo, ErrorResponse


class UploadLimitMiddleware:
    """ASGI receive limit; parser exceptions close already spooled temporary files."""

    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/api/tasks":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > self.max_bytes:
            payload = ErrorResponse(
                error=ErrorInfo(code="UPLOAD_TOO_LARGE", message="上传内容超过大小限制。")
            )
            return await JSONResponse(payload.model_dump(mode="json"), status_code=413)(
                scope, receive, send
            )
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                scope.setdefault("state", {})["upload_too_large"] = True
                raise MultiPartException("Upload exceeds configured limit")
            return message

        return await self.app(scope, limited_receive, send)
