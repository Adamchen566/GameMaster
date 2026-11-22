"""One error shape for the whole API: {"code": "...", "message": "..."}."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.game.errors import ErrorCode, RuleViolation


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


# 403: you are not the one who may do this. 409: not now. 422 (default): not like this.
_STATUS_BY_RULE = {
    ErrorCode.NOT_HOST: 403,
    ErrorCode.NOT_LEADER: 403,
    ErrorCode.NOT_ON_TEAM: 403,
    ErrorCode.NOT_ASSASSIN: 403,
    ErrorCode.WRONG_PHASE: 409,
    ErrorCode.STALE_VERSION: 409,
    ErrorCode.ALREADY_VOTED: 409,
}


def status_for(code: ErrorCode) -> int:
    return _STATUS_BY_RULE.get(code, 422)


def _body(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    def handle_api_error(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(_body(error.code, error.message), status_code=error.status_code)

    @app.exception_handler(RuleViolation)
    def handle_rule_violation(_: Request, error: RuleViolation) -> JSONResponse:
        return JSONResponse(_body(error.code, error.message), status_code=status_for(error.code))
