"""Domain errors raised by services and turned into HTTP answers in one place.

Every answer carries `detail` (a plain sentence for people) and `code` (a short, stable name
for programs such as ACE: `whatsapp_window_closed`, `email_opted_out`, `duplicate`…). Codes
never change once published; new ones may be added."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, detail: str, extra: dict | None = None, *, code: str | None = None):
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}  # more machine-readable facts for the client
        self.code = code or type(self).code


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class Invalid(DomainError):
    status_code = 422
    code = "invalid"


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code, **exc.extra}, status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        """A bug or an outage (a 500): staff are emailed (go-live G-2); the person sees a plain
        sentence, never the error."""
        from app.core.alerts import report

        host = request.headers.get("host", "").split(":")[0]
        await report(exc, context=f"{request.method} {request.url.path}"[:120], company=host)
        return JSONResponse(
            {
                "detail": "Something went wrong on our side. Please try again.",
                "code": "server_error",
            },
            status_code=500,
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid_input(_: Request, exc: RequestValidationError) -> JSONResponse:
        """A request body or parameter that doesn't fit (FastAPI's checks)."""
        return JSONResponse(
            {"detail": jsonable_encoder(exc.errors()), "code": "validation_error"},
            status_code=422,
        )
