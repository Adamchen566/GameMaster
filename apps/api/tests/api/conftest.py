"""Fixtures and helpers for driving the HTTP API the way the web client does."""

from __future__ import annotations

import itertools
import random
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_service
from app.game.repository import InMemoryGameRepository
from app.main import app
from app.rooms import InMemoryRoomStore
from app.service import GameService

Game = dict[str, Any]


@dataclass
class Backend:
    """A fresh, isolated service with deterministic seeds (1, 2, 3, ...)."""

    client: TestClient
    games: InMemoryGameRepository
    rooms: InMemoryRoomStore


@contextmanager
def isolated_backend() -> Iterator[Backend]:
    games = InMemoryGameRepository()
    rooms = InMemoryRoomStore()
    seeds = itertools.count(1)
    service = GameService(games, rooms, new_seed=lambda: next(seeds))

    app.dependency_overrides[get_service] = lambda: service
    try:
        yield Backend(client=TestClient(app), games=games, rooms=rooms)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def backend() -> Iterator[Backend]:
    with isolated_backend() as isolated:
        yield isolated


@dataclass
class Seat:
    """One human's connection to one game."""

    client: TestClient
    game_id: str
    token: str
    game: Game

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def post(self, **action: Any) -> Any:
        return self.client.post(f"/games/{self.game_id}/actions", json=action, headers=self.headers)

    def act(self, **action: Any) -> Game:
        response = self.post(**action)
        assert response.status_code == 200, response.text
        self.game = response.json()
        return self.game

    @property
    def me(self) -> dict[str, Any]:
        return next(player for player in self.game["players"] if player["is_you"])

    @property
    def legal(self) -> dict[str, Any] | None:
        actions = self.game["legal_actions"]
        return actions[0] if actions else None


def open_room(backend: Backend, player_count: int = 5, nickname: str = "Adam") -> Seat:
    response = backend.client.post(
        "/rooms", json={"nickname": nickname, "player_count": player_count}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Seat(
        client=backend.client, game_id=body["game_id"], token=body["token"], game=body["game"]
    )


def start_game(backend: Backend, player_count: int = 5) -> Seat:
    seat = open_room(backend, player_count)
    seat.act(type="start_game")
    return seat


def take_turn(seat: Seat, rng: random.Random) -> Game:
    """Play one legal action, chosen the way a cooperative human might."""
    legal = seat.legal
    assert legal is not None, "a running game must always be waiting for the human"
    version = seat.game["version"]

    match legal["type"]:
        case "propose_team":
            team = rng.sample(legal["targets"], legal["team_size"])
            return seat.act(type="propose_team", team=team, expected_version=version)
        case "speak":
            return seat.act(type="speak", text="No strong view yet.", expected_version=version)
        case "vote_team":
            return seat.act(type="vote_team", approve=rng.random() < 0.7, expected_version=version)
        case "vote_mission":
            success = not (legal["can_fail"] and rng.random() < 0.5)
            return seat.act(type="vote_mission", success=success, expected_version=version)
        case "assassinate":
            target = rng.choice(legal["targets"])
            return seat.act(type="assassinate", target_id=target, expected_version=version)
        case other:
            raise AssertionError(f"unexpected legal action {other}")


def play_until(
    backend: Backend,
    wanted: Callable[[Seat], bool],
    *,
    player_count: int = 5,
    attempts: int = 60,
) -> Seat:
    """Start games and play them until one reaches a position where `wanted` is true."""
    for attempt in range(attempts):
        seat = start_game(backend, player_count)
        rng = random.Random(attempt)
        while seat.game["phase"] != "finished":
            if wanted(seat):
                return seat
            take_turn(seat, rng)
    raise AssertionError("no game reached the wanted position")
