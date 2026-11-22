"""Structured logs: one JSON object per line, ids that join up, and no secrets."""

from __future__ import annotations

import io
import json
import logging
import random
import re
import sys
from collections.abc import Iterator
from typing import Any

import pytest

from app.agents.llm_player import LlmPlayer
from app.agents.model import TokenBudget
from app.evals.models import ScriptedModel
from app.game.actions import StartGame
from app.game.rulesets import Role
from app.gm.narrator import Narrator
from app.observability import (
    REQUEST_ID_HEADER,
    JsonFormatter,
    _request_id,
    configure_logging,
    current_request_id,
    event_id,
    in_current_context,
)
from app.service import GameService, InlineExecutor
from tests.api.conftest import Backend, isolated_backend, start_game, take_turn


@pytest.fixture
def backend() -> Iterator[Backend]:
    with isolated_backend() as isolated:
        yield isolated


def fields(record: logging.LogRecord) -> dict[str, Any]:
    line = json.loads(JsonFormatter().format(record))
    assert isinstance(line, dict)
    return line


def named(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, Any]]:
    return [fields(record) for record in caplog.records if record.getMessage() == event]


def one_action(seat: Any) -> dict[str, Any]:
    """Whatever the human may do right now, as a request body."""
    legal = seat.legal
    assert legal is not None
    body: dict[str, Any] = {"type": legal["type"], "expected_version": seat.game["version"]}
    match legal["type"]:
        case "propose_team":
            body["team"] = legal["targets"][: legal["team_size"]]
        case "speak":
            body["text"] = "Fine by me."
        case "vote_team":
            body["approve"] = True
        case "vote_mission":
            body["success"] = True
        case "assassinate":
            body["target_id"] = legal["targets"][0]
    return body


# --- The format --------------------------------------------------------------


def test_a_log_line_is_one_json_object_with_the_extra_fields() -> None:
    record = logging.makeLogRecord(
        {"name": "app.service", "levelname": "INFO", "msg": "events_appended", "game_id": "g1"}
    )

    line = fields(record)

    assert line["event"] == "events_appended"
    assert line["level"] == "info"
    assert line["logger"] == "app.service"
    assert line["game_id"] == "g1"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00", line["ts"])
    assert "request_id" not in line, "no request, no id"


def test_an_exception_is_kept_on_the_same_line() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.getLogger("app.test").makeRecord(
            "app.test", logging.ERROR, __file__, 1, "ai_turn_failed", (), sys.exc_info()
        )

    text = JsonFormatter().format(record)

    assert "\n" not in text
    assert "RuntimeError: boom" in json.loads(text)["exception"]


def test_configure_logging_writes_json_and_does_not_stack_handlers() -> None:
    logger = logging.getLogger("app")
    before = list(logger.handlers)
    try:
        configure_logging("json")
        handler = configure_logging("json")
        assert [h for h in logger.handlers if h not in before] == [handler]

        stream = io.StringIO()
        handler.setStream(stream)  # type: ignore[attr-defined]
        logging.getLogger("app.anything").info("hello", extra={"game_id": "g9"})
        assert json.loads(stream.getvalue())["game_id"] == "g9"

        text_handler = configure_logging("text", "warning")
        assert not isinstance(text_handler.formatter, JsonFormatter)
        assert logger.level == logging.WARNING
    finally:
        for handler in list(logger.handlers):
            if handler not in before:
                logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)


def test_event_id_is_the_game_and_the_version() -> None:
    assert event_id("g1", 12) == "g1:12"


# --- Request ids -------------------------------------------------------------


def test_every_response_carries_a_request_id(backend: Backend) -> None:
    first = backend.client.get("/health").headers[REQUEST_ID_HEADER]
    second = backend.client.get("/health").headers[REQUEST_ID_HEADER]

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second


def test_a_sane_incoming_request_id_is_kept(backend: Backend) -> None:
    response = backend.client.get("/health", headers={REQUEST_ID_HEADER: "edge-7f3a.1"})

    assert response.headers[REQUEST_ID_HEADER] == "edge-7f3a.1"


@pytest.mark.parametrize("supplied", ["has space", "x" * 65, 'quote"injection', "new\tline", ""])
def test_an_unsafe_incoming_request_id_is_replaced(backend: Backend, supplied: str) -> None:
    response = backend.client.get("/health", headers={REQUEST_ID_HEADER: supplied})

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers[REQUEST_ID_HEADER])


def test_error_responses_carry_the_id_too(backend: Backend) -> None:
    response = backend.client.get("/games/nope", headers={REQUEST_ID_HEADER: "trace-1"})

    assert response.status_code == 401
    assert response.headers[REQUEST_ID_HEADER] == "trace-1"


def test_the_request_line_has_method_path_status_and_duration(
    backend: Backend, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app")

    backend.client.get("/health", headers={REQUEST_ID_HEADER: "trace-2"})

    (line,) = named(caplog, "http_request")
    assert (line["method"], line["path"], line["status"]) == ("GET", "/health", 200)
    assert line["duration_ms"] >= 0
    assert current_request_id() is None, "the id does not outlive the request"


# --- Joining a request to the game and its events ------------------------------


def test_an_action_is_logged_with_the_request_game_and_event_ids(
    backend: Backend, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app")
    seat = start_game(backend)
    caplog.clear()

    before = seat.game["version"]
    backend.client.post(
        f"/games/{seat.game_id}/actions",
        json=one_action(seat),
        headers={**seat.headers, REQUEST_ID_HEADER: "trace-3"},
    )

    (appended,) = named(caplog, "events_appended")
    assert appended["game_id"] == seat.game_id
    assert appended["version"] > before
    assert appended["event_id"] == f"{seat.game_id}:{appended['version']}"
    assert appended["actor"] == "p1"
    assert appended["events"] and all(isinstance(name, str) for name in appended["events"])

    by_record = {record.getMessage(): record for record in caplog.records}
    assert "http_request" in by_record
    # Both lines were written inside the same request context.
    assert fields(by_record["http_request"])["path"].endswith("/actions")


def test_logs_of_a_whole_game_hold_no_secrets(
    backend: Backend, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="app")
    seat = start_game(backend, 7)
    rng = random.Random(5)
    while seat.game["phase"] != "finished":
        take_turn(seat, rng)

    text = "\n".join(JsonFormatter().format(record) for record in caplog.records)

    assert seat.token not in text
    for role in Role:
        assert f'"{role.value}"' not in text
    assert '"roles"' not in text and '"success"' not in text
    assert "GameStarted" in text and "GameFinished" in text


# --- Work that continues after the request -------------------------------------


def test_background_work_keeps_the_id_of_the_request_that_started_it() -> None:
    seen: list[str | None] = []
    token = _request_id.set("trace-4")
    try:
        task = in_current_context(lambda: seen.append(current_request_id()))
    finally:
        _request_id.reset(token)

    task()

    assert seen == ["trace-4"]
    assert current_request_id() is None


def test_an_ai_turn_is_logged_with_its_source_and_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app")
    budget = TokenBudget(10**9)
    service = GameService(
        llm_players={"baseline": LlmPlayer(ScriptedModel(), budget)},
        narrator=Narrator(),
        budget=budget,
        executor=InlineExecutor(),
        new_seed=lambda: 3,
    )
    created = service.create_room("Adam", 5, ai_seats=4)
    service.submit(created.session, StartGame(player_id="p1", seed=3))

    turns = named(caplog, "ai_turn")
    game_id = created.session.room.game_id

    assert turns, "four model seats cannot all be waiting for the human"
    for turn in turns:
        assert turn["game_id"] == game_id
        assert turn["event_id"].startswith(f"{game_id}:")
        assert turn["agent"] == "llm"
        assert turn["source"] == "model"
        assert turn["fallback_reason"] is None
        assert turn["duration_ms"] >= 0
        assert "note" not in turn


def test_lines_written_during_a_request_carry_its_id(backend: Backend) -> None:
    """End to end: the real handler, the real middleware, a service call on a worker thread."""
    logger = logging.getLogger("app")
    before = list(logger.handlers)
    handler = configure_logging("json")
    stream = io.StringIO()
    handler.setStream(stream)  # type: ignore[attr-defined]
    try:
        seat = start_game(backend)
        stream.seek(0)
        stream.truncate()
        response = backend.client.post(
            f"/games/{seat.game_id}/actions",
            json=one_action(seat),
            headers={**seat.headers, REQUEST_ID_HEADER: "trace-5"},
        )
        assert response.status_code == 200
    finally:
        logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)
        assert logger.handlers == before

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]

    assert [line["event"] for line in lines] == ["events_appended", "http_request"]
    assert {line["request_id"] for line in lines} == {"trace-5"}
    assert lines[0]["game_id"] == seat.game_id
    assert seat.token not in stream.getvalue()
