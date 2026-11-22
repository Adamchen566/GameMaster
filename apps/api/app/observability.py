"""Structured logs with ids that tie a request, a game and an event together.

Every log line is one JSON object. Three ids make lines findable:

- `request_id`  one HTTP request. Taken from `X-Request-ID` when a proxy sent a
                sane one, generated otherwise, and returned in the response.
- `game_id`     the game a line is about.
- `event_id`    `{game_id}:{version}`, the same key the game master uses.

Work that a request starts on another thread (model turns, narration) keeps the
id of the request that started it; see `in_current_context`.

Logs never contain tokens, roles, mission cards or a model's private notes:
only ids, counts, event *type* names and outcomes.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, Request, Response

REQUEST_ID_HEADER = "X-Request-ID"
_ACCEPTABLE_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed through `extra=`.
_STANDARD = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

log = logging.getLogger(__name__)


def current_request_id() -> str | None:
    return _request_id.get()


def event_id(game_id: str, version: int) -> str:
    return f"{game_id}:{version}"


def in_current_context(task: Callable[[], None]) -> Callable[[], None]:
    """Wrap `task` so it runs later, elsewhere, with the ids of whoever scheduled it."""
    context = contextvars.copy_context()
    return lambda: context.run(task)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        request_id = current_request_id()
        if request_id is not None:
            line["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                line[key] = value
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False, default=str)


def configure_logging(
    log_format: Literal["json", "text"] = "json", level: str = "INFO"
) -> logging.Handler:
    """Send this application's logs to stderr. Safe to call more than once."""
    logger = logging.getLogger("app")
    for handler in list(logger.handlers):
        if getattr(handler, "_avalon", False):
            logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler._avalon = True  # type: ignore[attr-defined]
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    return handler


def _request_id_from(request: Request) -> str:
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    # A client-chosen id is echoed into logs, so only a short, plain one is kept.
    return supplied if _ACCEPTABLE_ID.fullmatch(supplied) else uuid4().hex


def install_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id_from(request)
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            log.info(
                "http_request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            _request_id.reset(token)
