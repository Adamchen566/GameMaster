import pytest

from app.game.repository import GameNotFound, InMemoryGameRepository, VersionConflict
from app.game.simulate import play_random_game
from tests.game.scenarios import lobby, started


def test_new_game_is_stored_in_its_lobby_state() -> None:
    repository = InMemoryGameRepository()
    initial = lobby()

    repository.create(initial)

    assert repository.load(initial.game_id) == initial
    assert repository.events(initial.game_id) == ()


def test_game_cannot_be_created_twice() -> None:
    repository = InMemoryGameRepository()
    repository.create(lobby())

    with pytest.raises(ValueError, match="already exists"):
        repository.create(lobby())


def test_game_must_be_stored_before_it_starts() -> None:
    with pytest.raises(ValueError, match="before any event"):
        InMemoryGameRepository().create(started())


def test_unknown_game_is_reported_by_every_method() -> None:
    repository = InMemoryGameRepository()

    for call in (
        lambda: repository.load("nope"),
        lambda: repository.events("nope"),
        lambda: repository.append("nope", 0, []),
    ):
        with pytest.raises(GameNotFound) as error:
            call()
        assert error.value.game_id == "nope"


def test_appended_events_rebuild_the_same_state_as_the_engine() -> None:
    game = play_random_game(player_count=7, seed=4)
    repository = InMemoryGameRepository()
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

    assert repository.load(game_id) == game.final
    assert repository.events(game_id) == game.events


def test_append_from_a_stale_version_is_refused_and_stores_nothing() -> None:
    game = play_random_game(player_count=5, seed=2)
    repository = InMemoryGameRepository()
    repository.create(game.initial)
    game_id = game.initial.game_id
    repository.append(game_id, 0, game.events[:2])

    with pytest.raises(VersionConflict) as error:
        repository.append(game_id, 0, game.events[2:3])

    assert (error.value.expected, error.value.actual) == (0, 2)
    assert error.value.game_id == game_id
    assert repository.events(game_id) == game.events[:2]
