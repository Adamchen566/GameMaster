"""`RoomStore` on SQL."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Connection, insert, select

from app.rooms import Room, Seat
from app.storage.database import Database
from app.storage.schema import room_players, rooms


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqlRoomStore:
    def __init__(self, database: Database, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._database = database
        self._now = now

    def add(self, room: Room) -> None:
        room_id = uuid4().hex
        with self._database.transaction() as connection:
            connection.execute(
                insert(rooms).values(
                    id=room_id,
                    game_id=room.game_id,
                    code=room.code,
                    seed=room.seed,
                    created_at=self._now(),
                    gm_mode=room.gm,
                    language=room.language,
                )
            )
            connection.execute(
                insert(room_players),
                [
                    {
                        "room_id": room_id,
                        "seat": seat_number,
                        "player_id": seat.player_id,
                        "name": seat.name,
                        "is_bot": seat.is_bot,
                        "token_hash": seat.token_hash,
                        "agent": seat.agent,
                        "agent_style": seat.style,
                    }
                    for seat_number, seat in enumerate(room.seats)
                ],
            )

    def by_game_id(self, game_id: str) -> Room | None:
        with self._database.transaction() as connection:
            room_id = connection.execute(
                select(rooms.c.id).where(rooms.c.game_id == game_id)
            ).scalar_one_or_none()
            return None if room_id is None else self._room(connection, room_id)

    def by_token_hash(self, token_hash: str) -> tuple[Room, Seat] | None:
        with self._database.transaction() as connection:
            room_id = connection.execute(
                select(room_players.c.room_id).where(room_players.c.token_hash == token_hash)
            ).scalar_one_or_none()
            if room_id is None:
                return None
            room = self._room(connection, room_id)
            seat = next(seat for seat in room.seats if seat.token_hash == token_hash)
            return room, seat

    def _room(self, connection: Connection, room_id: str) -> Room:
        room = connection.execute(
            select(
                rooms.c.code, rooms.c.game_id, rooms.c.seed, rooms.c.gm_mode, rooms.c.language
            ).where(rooms.c.id == room_id)
        ).one()
        seats = connection.execute(
            select(
                room_players.c.player_id,
                room_players.c.name,
                room_players.c.is_bot,
                room_players.c.token_hash,
                room_players.c.agent,
                room_players.c.agent_style,
            )
            .where(room_players.c.room_id == room_id)
            .order_by(room_players.c.seat)
        )
        return Room(
            code=room.code,
            game_id=room.game_id,
            seed=room.seed,
            seats=tuple(
                Seat(
                    player_id=seat.player_id,
                    name=seat.name,
                    is_bot=seat.is_bot,
                    token_hash=seat.token_hash,
                    agent=seat.agent,
                    style=seat.agent_style,
                )
                for seat in seats
            ),
            gm=room.gm_mode,
            language=room.language,
        )
