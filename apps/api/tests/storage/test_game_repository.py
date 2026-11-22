"""The repository contract, checked against every implementation, plus what
only a database can promise (durability, constraints, concurrent writers)."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.game.repository import GameNotFound, GameRepository, VersionConflict
from app.game.simulate import play_random_game
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from app.storage.schema import game_events, games
from tests.game.scenarios import lobby, started

# --- Contract: in memory, SQLite and PostgreSQL ------------------------------


def test_new_game_is_stored_in_its_lobby_state(repository: GameRepository) -> None:
    initial = lobby()

    repository.create(initial)

    assert repository.load(initial.game_id) == initial
    assert repository.events(initial.game_id) == ()


def test_game_cannot_be_created_twice(repository: GameRepository) -> None:
    repository.create(lobby())

    with pytest.raises(ValueError, match="already exists"):
        repository.create(lobby())


def test_game_must_be_stored_before_it_starts(repository: GameRepository) -> None:
    with pytest.raises(ValueError, match="before any event"):
        repository.create(started())


def test_unknown_game_is_reported_by_every_method(repository: GameRepository) -> None:
    for call in (
        lambda: repository.load("nope"),
        lambda: repository.events("nope"),
        lambda: repository.append("nope", 0, []),
    ):
        with pytest.raises(GameNotFound) as error:
            call()
        assert error.value.game_id == "nope"


@pytest.mark.parametrize("player_count", [5, 7, 10])
def test_appended_events_rebuild_the_same_state_as_the_engine(
    repository: GameRepository, player_count: int
) -> None:
    game = play_random_game(player_count=player_count, seed=4)
    repository.create(game.initial)
    game_id = game.initial.game_id

    # Append in uneven batches, the way real requests would.
    position = 0
    for batch_size in [2, 1, 5, 3] * len(game.events):
        batch = game.events[position : position + batch_size]
        if not batch:
            break
        state = repository.append(game_id, position, batch)
        position += len(batch)
        assert state.version == position
        assert repository.load(game_id) == state

    assert repository.load(game_id) == game.final
    assert repository.events(game_id) == game.events


def test_append_from_a_stale_version_is_refused_and_stores_nothing(
    repository: GameRepository,
) -> None:
    game = play_random_game(player_count=5, seed=2)
    repository.create(game.initial)
    game_id = game.initial.game_id
    repository.append(game_id, 0, game.events[:2])

    with pytest.raises(VersionConflict) as error:
        repository.append(game_id, 0, game.events[2:3])

    assert (error.value.expected, error.value.actual) == (0, 2)
    assert error.value.game_id == game_id
    assert repository.events(game_id) == game.events[:2]


def test_append_from_a_future_version_is_refused(repository: GameRepository) -> None:
    game = play_random_game(player_count=5, seed=2)
    repository.create(game.initial)

    with pytest.raises(VersionConflict) as error:
        repository.append(game.initial.game_id, 3, game.events[:1])

    assert (error.value.expected, error.value.actual) == (3, 0)


def test_appending_nothing_changes_nothing(repository: GameRepository) -> None:
    initial = lobby()
    repository.create(initial)

    assert repository.append(initial.game_id, 0, []) == initial
    assert repository.events(initial.game_id) == ()


def test_games_do_not_share_events(repository: GameRepository) -> None:
    first = play_random_game(player_count=5, seed=1)
    second_initial = replace(lobby(6), game_id="game-2")
    repository.create(first.initial)
    repository.create(second_initial)

    repository.append(first.initial.game_id, 0, first.events)

    assert repository.load("game-2") == second_initial
    assert repository.load(first.initial.game_id) == first.final


# --- SQL only ----------------------------------------------------------------


def test_game_survives_a_restart(url: str) -> None:
    game = play_random_game(player_count=8, seed=11)
    half = len(game.events) // 2

    before = Database.from_url(url)
    writer = SqlGameRepository(before)
    writer.create(game.initial)
    writer.append(game.initial.game_id, 0, game.events[:half])
    before.dispose()

    # A new process: nothing but the database carries over.
    after = Database.from_url(url)
    reader = SqlGameRepository(after)
    assert reader.events(game.initial.game_id) == game.events[:half]
    assert reader.append(game.initial.game_id, half, game.events[half:]) == game.final
    assert reader.load(game.initial.game_id) == game.final
    after.dispose()


def test_finishing_a_game_records_the_result_on_the_game_row(database: Database) -> None:
    game = play_random_game(player_count=5, seed=3)
    created = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
    clock = iter([created, created + timedelta(minutes=1), created + timedelta(minutes=25)])
    repository = SqlGameRepository(database, now=lambda: next(clock))
    game_id = game.initial.game_id

    repository.create(game.initial)
    repository.append(game_id, 0, game.events[:-1])
    with database.transaction() as connection:
        running = connection.execute(select(games).where(games.c.id == game_id)).one()
    assert (running.version, running.winner, running.win_reason, running.finished_at) == (
        len(game.events) - 1,
        None,
        None,
        None,
    )

    repository.append(game_id, len(game.events) - 1, game.events[-1:])
    with database.transaction() as connection:
        finished = connection.execute(select(games).where(games.c.id == game_id)).one()

    assert game.final.winner is not None and game.final.win_reason is not None
    assert finished.version == len(game.events)
    assert finished.winner == game.final.winner.value
    assert finished.win_reason == game.final.win_reason.value
    # SQLite returns naive datetimes; compare wall-clock values.
    assert finished.finished_at.replace(tzinfo=UTC) - finished.created_at.replace(
        tzinfo=UTC
    ) == timedelta(minutes=25)


def test_event_versions_are_gapless_and_start_at_one(database: Database) -> None:
    game = play_random_game(player_count=6, seed=5)
    repository = SqlGameRepository(database)
    repository.create(game.initial)
    repository.append(game.initial.game_id, 0, game.events[:4])
    repository.append(game.initial.game_id, 4, game.events[4:])

    with database.transaction() as connection:
        versions = connection.execute(
            select(game_events.c.version).order_by(game_events.c.version)
        ).scalars()
        assert list(versions) == list(range(1, len(game.events) + 1))


def test_database_refuses_a_second_event_with_the_same_version(database: Database) -> None:
    game = play_random_game(player_count=5, seed=2)
    repository = SqlGameRepository(database)
    repository.create(game.initial)
    repository.append(game.initial.game_id, 0, game.events[:1])

    # Even code that skips the repository cannot fork the log.
    with pytest.raises(IntegrityError), database.transaction() as connection:
        connection.execute(
            insert(game_events).values(
                game_id=game.initial.game_id,
                version=1,
                type="team_vote_cast",
                payload={"player_id": "p1", "approve": True},
                created_at=datetime.now(UTC),
            )
        )


def test_database_refuses_an_event_for_a_game_that_does_not_exist(database: Database) -> None:
    with pytest.raises(IntegrityError), database.transaction() as connection:
        connection.execute(
            insert(game_events).values(
                game_id="ghost",
                version=1,
                type="team_vote_cast",
                payload={"player_id": "p1", "approve": True},
                created_at=datetime.now(UTC),
            )
        )


def test_failed_transaction_leaves_no_trace(database: Database) -> None:
    game = play_random_game(player_count=5, seed=2)
    repository = SqlGameRepository(database)
    repository.create(game.initial)

    with pytest.raises(RuntimeError, match="boom"), database.transaction():
        repository.append(game.initial.game_id, 0, game.events[:3])
        raise RuntimeError("boom")

    assert repository.load(game.initial.game_id) == game.initial
    assert repository.events(game.initial.game_id) == ()


def test_only_one_of_many_concurrent_writers_wins(pg_database: Database) -> None:
    """Real row locking: every writer loaded version 0, exactly one may append."""
    game = play_random_game(player_count=5, seed=2)
    game_id = game.initial.game_id
    repository = SqlGameRepository(pg_database)
    repository.create(game.initial)

    writers = 8
    ready = threading.Barrier(writers)
    outcomes: list[str] = []

    def write() -> None:
        ready.wait()
        try:
            repository.append(game_id, 0, game.events[:2])
            outcomes.append("stored")
        except VersionConflict as conflict:
            assert (conflict.expected, conflict.actual) == (0, 2)
            outcomes.append("conflict")

    threads = [threading.Thread(target=write) for _ in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["conflict"] * (writers - 1) + ["stored"]
    assert repository.events(game_id) == game.events[:2]
