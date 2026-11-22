from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from app.game.engine import new_game
from app.game.repository import GameRepository
from app.game.rulesets import OFFICIAL
from app.rooms import Room, RoomStore, Seat, hash_token
from app.service import GameService
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from app.storage.rooms import SqlRoomStore
from app.storage.schema import game_events, games, room_players, rooms

Stores = tuple[GameRepository, RoomStore]


def make_room(game_id: str = "game-1", token: str = "token-1") -> Room:
    return Room(
        code="ABC234",
        game_id=game_id,
        seed=2**62 + 12345,  # must fit a 64-bit column without losing digits
        gm="ai",
        language="en",
        seats=(
            Seat(player_id="p1", name="Adam", is_bot=False, token_hash=hash_token(token)),
            *(
                Seat(
                    player_id=f"p{number}",
                    name=f"Bot {number}",
                    is_bot=True,
                    # One model seat with a style, the rest random bots.
                    agent="llm" if number == 2 else "random",
                    style="cautious" if number == 2 else None,
                )
                for number in range(2, 6)
            ),
        ),
    )


def store_room(stores: Stores, room: Room) -> None:
    games_repository, room_store = stores
    games_repository.create(
        new_game(
            game_id=room.game_id,
            ruleset=OFFICIAL,
            player_ids=[seat.player_id for seat in room.seats],
            host_id=room.seats[0].player_id,
        )
    )
    room_store.add(room)


# --- Contract: in memory, SQLite and PostgreSQL ------------------------------


def test_room_is_found_by_its_game_with_seats_in_order(stores: Stores) -> None:
    room = make_room()
    store_room(stores, room)

    assert stores[1].by_game_id("game-1") == room


def test_human_seat_is_found_by_its_token_digest(stores: Stores) -> None:
    room = make_room(token="secret")
    store_room(stores, room)

    assert stores[1].by_token_hash(hash_token("secret")) == (room, room.seats[0])


def test_unknown_game_and_unknown_token_find_nothing(stores: Stores) -> None:
    store_room(stores, make_room())

    assert stores[1].by_game_id("other") is None
    assert stores[1].by_token_hash(hash_token("wrong")) is None


def test_each_token_leads_to_its_own_room(stores: Stores) -> None:
    first = make_room("game-1", "token-1")
    second = make_room("game-2", "token-2")
    store_room(stores, first)
    store_room(stores, second)

    assert stores[1].by_token_hash(hash_token("token-2")) == (second, second.seats[0])
    assert stores[1].by_game_id("game-1") == first


# --- SQL only: what the constraints promise ----------------------------------


def _sql(database: Database) -> Stores:
    return SqlGameRepository(database), SqlRoomStore(database)


def _count(database: Database, table: object) -> int:
    with database.transaction() as connection:
        return connection.execute(select(func.count()).select_from(table)).scalar_one()  # type: ignore[arg-type]


def test_token_itself_is_never_stored(database: Database) -> None:
    store_room(_sql(database), make_room(token="plain-token"))

    with database.transaction() as connection:
        stored = connection.execute(select(room_players)).all()

    assert "plain-token" not in repr(stored)
    assert hash_token("plain-token") in repr(stored)


def test_room_needs_an_existing_game(database: Database) -> None:
    with pytest.raises(IntegrityError):
        SqlRoomStore(database).add(make_room("no-such-game"))

    assert _count(database, rooms) == 0
    assert _count(database, room_players) == 0


def test_player_cannot_exist_without_a_room(database: Database) -> None:
    with pytest.raises(IntegrityError), database.transaction() as connection:
        connection.execute(
            insert(room_players).values(
                room_id="ghost-room",
                seat=0,
                player_id="p1",
                name="Adam",
                is_bot=True,
                agent="random",
            )
        )


def test_game_can_only_have_one_room(database: Database) -> None:
    stores = _sql(database)
    store_room(stores, make_room("game-1", "token-1"))

    with pytest.raises(IntegrityError):
        stores[1].add(make_room("game-1", "token-2"))

    # The failed room left nothing behind, not even its seats.
    assert _count(database, rooms) == 1
    assert _count(database, room_players) == 5


def test_two_seats_cannot_share_a_token(database: Database) -> None:
    stores = _sql(database)
    store_room(stores, make_room("game-1", "same"))

    with pytest.raises(IntegrityError):
        store_room(stores, make_room("game-2", "same"))


@pytest.mark.parametrize(
    "seat",
    [
        {"is_bot": True, "token_hash": "abc", "agent": "random"},  # a bot that could log in
        {"is_bot": False, "token_hash": None, "agent": None},  # a human who never can
        {"is_bot": True, "token_hash": None, "agent": None},  # a bot nobody plays
        {"is_bot": False, "token_hash": "abc", "agent": "llm"},  # a human played by a model
    ],
)
def test_seat_is_either_a_human_with_a_token_or_a_bot_with_an_agent(
    database: Database, seat: dict[str, object]
) -> None:
    stores = _sql(database)
    store_room(stores, make_room())
    with database.transaction() as connection:
        room_id = connection.execute(select(rooms.c.id)).scalar_one()

    with pytest.raises(IntegrityError), database.transaction() as connection:
        connection.execute(
            insert(room_players).values(
                room_id=room_id, seat=9, player_id="p10", name="Extra", **seat
            )
        )


def test_deleting_a_game_removes_its_room_players_and_events(database: Database) -> None:
    service = GameService(*_sql(database), transaction=database.transaction)
    created = service.create_room("Adam", 5)
    keep = service.create_room("Eve", 5)
    game_id = created.session.room.game_id
    with database.transaction() as connection:
        connection.execute(
            insert(game_events).values(
                game_id=game_id,
                version=1,
                type="team_vote_cast",
                payload={"player_id": "p1", "approve": True},
                created_at=datetime.now(UTC),
            )
        )

    with database.transaction() as connection:
        connection.execute(delete(games).where(games.c.id == game_id))

    assert _count(database, games) == 1
    assert _count(database, rooms) == 1
    assert _count(database, room_players) == 5
    assert _count(database, game_events) == 0
    assert service.authenticate(created.token) is None
    assert service.authenticate(keep.token) is not None


# --- The service's unit of work ----------------------------------------------


class _BrokenRoomStore(SqlRoomStore):
    def add(self, room: Room) -> None:
        super().add(room)
        raise RuntimeError("crashed after writing the room")


class _UnreachableRoomStore(SqlRoomStore):
    def add(self, room: Room) -> None:
        raise RuntimeError("crashed before writing the room")


def test_room_and_game_are_stored_together_or_not_at_all(database: Database) -> None:
    repository = SqlGameRepository(database)
    service = GameService(repository, _BrokenRoomStore(database), transaction=database.transaction)

    with pytest.raises(RuntimeError, match="crashed"):
        service.create_room("Adam", 5)

    assert _count(database, games) == 0
    assert _count(database, rooms) == 0
    assert _count(database, room_players) == 0


def test_without_a_shared_transaction_a_crash_would_leave_a_game_behind(
    database: Database,
) -> None:
    """Why `transaction=` exists: this is the failure it prevents."""
    repository = SqlGameRepository(database)
    service = GameService(repository, _UnreachableRoomStore(database))

    with pytest.raises(RuntimeError, match="crashed"):
        service.create_room("Adam", 5)

    assert _count(database, games) == 1
    assert _count(database, rooms) == 0
