"""Runs sql/queries.sql against PostgreSQL and checks each answer against the
engine's own state, so the documented queries cannot rot."""

from __future__ import annotations

import itertools
import random
import re
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.agents.policy_fallback import choose_action
from app.game.actions import StartGame
from app.game.state import GameState
from app.service import CreatedRoom, GameService
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from app.storage.rooms import SqlRoomStore
from tests.storage.conftest import API_ROOT


def load_queries() -> dict[str, str]:
    source = (API_ROOT / "sql" / "queries.sql").read_text(encoding="utf-8")
    parts = re.split(r"^-- name: (\w+)\n", source, flags=re.MULTILINE)
    return dict(zip(parts[1::2], (body.strip() for body in parts[2::2]), strict=True))


QUERIES = load_queries()


def test_file_contains_the_five_documented_queries() -> None:
    assert list(QUERIES) == [
        "room_players",
        "game_durations",
        "mission_results",
        "player_win_rates",
        "recent_events",
    ]


class Played:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = SqlGameRepository(database)
        seeds = itertools.count(1)
        self.service = GameService(
            self.repository,
            SqlRoomStore(database),
            transaction=database.transaction,
            new_seed=lambda: next(seeds),
        )

    def play(self, nickname: str, player_count: int = 5, *, finish: bool = True) -> GameState:
        created = self.service.create_room(nickname, player_count)
        self.finish(created, finish=finish)
        return self.repository.load(created.session.room.game_id)

    def finish(self, created: CreatedRoom, *, finish: bool) -> None:
        session = created.session
        rng = random.Random(session.room.seed)
        view = self.service.submit(session, StartGame(player_id="p1", seed=session.room.seed))
        turns = 0
        while view.legal_actions and (finish or turns < 3):
            view = self.service.submit(session, choose_action(view, rng))
            turns += 1

    def run(self, name: str, **parameters: Any) -> list[Any]:
        with self.database.transaction() as connection:
            return list(connection.execute(text(QUERIES[name]), parameters))


@pytest.fixture
def played(pg_database: Database) -> Played:
    return Played(pg_database)


def test_room_players_lists_the_seats_in_order(played: Played) -> None:
    state = played.play("Adam", 6, finish=False)
    played.play("Eve", 5, finish=False)

    rows = played.run("room_players", game_id=state.game_id)

    assert [(row.seat, row.player_id, row.is_bot) for row in rows] == [
        (seat, f"p{seat + 1}", seat != 0) for seat in range(6)
    ]
    assert rows[0].name == "Adam"


def test_game_durations_only_counts_finished_games(played: Played) -> None:
    finished = [played.play("Adam"), played.play("Adam", 7)]
    played.play("Adam", finish=False)

    rows = played.run("game_durations")

    assert {row.game_id for row in rows} == {state.game_id for state in finished}
    by_id = {row.game_id: row for row in rows}
    for state in finished:
        row = by_id[state.game_id]
        assert state.winner is not None and state.win_reason is not None
        assert (row.winner, row.win_reason) == (state.winner.value, state.win_reason.value)
        assert row.event_count == state.version
        assert timedelta(0) <= row.duration < timedelta(minutes=1)


def test_mission_results_match_the_engine(played: Played) -> None:
    state = played.play("Adam", 8)
    played.play("Eve", 5)

    rows = played.run("mission_results", game_id=state.game_id)

    completed = [
        (mission.number, mission.outcome.value, mission.fail_votes)
        for mission in state.missions
        if mission.outcome is not None
    ]
    assert len(completed) >= 3
    assert [(row.mission_number, row.outcome, row.fail_votes) for row in rows] == completed


def test_player_win_rates_match_a_count_done_in_python(played: Played) -> None:
    expected: dict[str, list[int]] = {}
    for nickname in ["Adam", "Adam", "Adam", "Eve", "Eve", "Adam"]:
        state = played.play(nickname)
        human = next(player for player in state.players if player.id == "p1")
        assert human.role is not None and state.winner is not None
        tally = expected.setdefault(nickname, [0, 0])
        tally[0] += 1
        tally[1] += human.role.alignment is state.winner
    played.play("Unfinished", finish=False)

    rows = played.run("player_win_rates")

    assert {row.name: [row.games, row.wins] for row in rows} == expected
    for row in rows:
        assert float(row.win_rate) == round(row.wins / row.games, 3)
    assert [float(row.win_rate) for row in rows] == sorted(
        (float(row.win_rate) for row in rows), reverse=True
    )


def test_recent_events_returns_the_last_twenty_newest_first(played: Played) -> None:
    state = played.play("Adam", 10)
    assert state.version > 20

    rows = played.run("recent_events", game_id=state.game_id)

    assert [row.version for row in rows] == list(range(state.version, state.version - 20, -1))
    assert rows[0].type == "game_finished"
    assert rows[0].payload["winner"] in {"good", "evil"}
