"""Domain errors raised by services and turned into HTTP answers in one place."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400

    def __init__(self, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}  # more machine-readable facts for the client


class Forbidden(DomainError):
    status_code = 403


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class Invalid(DomainError):
    status_code = 422


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail, **exc.extra}, status_code=exc.status_code)
