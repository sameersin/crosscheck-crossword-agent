"""Local-host protection, actual request-body bounds, and response security headers."""

from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from crossword_agent.domain import PuzzleValidationError


class BodySizeLimitMiddleware:
    """Bound actual body bytes before JSON/multipart parsing, including chunked uploads."""

    def __init__(self, app: ASGIApp, max_image_bytes: int):
        self.app = app
        self.max_image_bytes = max_image_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return
        image_upload = scope["path"] == "/api/extract" or (
            scope["path"].startswith("/api/runs/") and scope["path"].endswith("/reference-image")
        )
        limit = self.max_image_bytes + 100000 if image_upload else 512000
        lengths = [
            value for key, value in scope.get("headers", []) if key.lower() == b"content-length"
        ]
        try:
            if len(lengths) > 1:
                raise ValueError("Repeated content length")
            declared = int(lengths[0]) if lengths else 0
            if declared < 0:
                raise ValueError("Negative content length")
        except ValueError:
            await JSONResponse(status_code=400, content={"detail": "Invalid content length."})(
                scope, receive, send
            )
            return
        if declared > limit:
            await JSONResponse(
                status_code=413, content={"detail": "Upload exceeds the allowed size."}
            )(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                await JSONResponse(
                    status_code=413, content={"detail": "Upload exceeds the allowed size."}
                )(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        payload = bytes(body)
        del body
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def configure_http_boundary(app: FastAPI, *, max_image_bytes: int) -> None:
    """Install the same ordered boundary around every route and static response."""
    app.add_middleware(BodySizeLimitMiddleware, max_image_bytes=max_image_bytes)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin write requests are not allowed."},
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(PuzzleValidationError)
    async def invalid_puzzle(_request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})
