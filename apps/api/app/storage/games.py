"""`GameRepository` on SQL: one row per game, one row per event."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy import Connection, insert, select, update

from app.game.codec import decode_event, encode_event
from app.game.engine import new_game, replay
from app.game.events import GameEvent, GameFinished
from app.game.repository import GameNotFound, VersionConflict
from app.game.rulesets import get_ruleset
from app.game.state import GameState
from app.storage.database import Database
from app.storage.schema import game_events, games


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqlGameRepository:
    def __init__(self, database: Database, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._database = database
        self._now = now

    def create(self, initial: GameState) -> None:
        if initial.version != 0:
            raise ValueError("A new game must be stored before any event is applied.")

        with self._database.transaction() as connection:
            exists = connection.execute(
                select(games.c.id).where(games.c.id == initial.game_id)
            ).one_or_none()
            if exists is not None:
                raise ValueError(f"Game '{initial.game_id}' already exists.")
            connection.execute(
                insert(games).values(
                    id=initial.game_id,
                    ruleset_id=initial.ruleset.id,
                    host_id=initial.host_id,
                    player_ids=[player.id for player in initial.players],
                    version=0,
                    created_at=self._now(),
                )
            )

    def load(self, game_id: str) -> GameState:
        with self._database.transaction() as connection:
            return self._load(connection, game_id)

    def events(self, game_id: str) -> tuple[GameEvent, ...]:
        with self._database.transaction() as connection:
            self._initial(connection, game_id)
            return self._events(connection, game_id)

    def append(self, game_id: str, expected_version: int, events: Sequence[GameEvent]) -> GameState:
        with self._database.transaction() as connection:
            current = self._load(connection, game_id)
            if current.version != expected_version:
                raise VersionConflict(game_id, expected_version, current.version)
            if not events:
                return current

            # Replaying first means events that do not fit the state are never stored.
            state = replay(current, events)
            now = self._now()
            finished = next((e for e in events if isinstance(e, GameFinished)), None)

            # The version check and the bump are one statement. Two writers that
            # both loaded version N race for this row: the database lets one
            # through and the other matches zero rows.
            claimed = connection.execute(
                update(games)
                .where(games.c.id == game_id, games.c.version == expected_version)
                .values(
                    version=state.version,
                    **(
                        {
                            "winner": finished.winner.value,
                            "win_reason": finished.reason.value,
                            "finished_at": now,
                        }
                        if finished is not None
                        else {}
                    ),
                )
            )
            if claimed.rowcount != 1:
                actual = connection.execute(
                    select(games.c.version).where(games.c.id == game_id)
                ).scalar_one()
                raise VersionConflict(game_id, expected_version, actual)

            rows = []
            for offset, event in enumerate(events, start=1):
                event_type, payload = encode_event(event)
                rows.append(
                    {
                        "game_id": game_id,
                        "version": expected_version + offset,
                        "type": event_type,
                        "payload": payload,
                        "created_at": now,
                    }
                )
            connection.execute(insert(game_events), rows)
            return state

    def _initial(self, connection: Connection, game_id: str) -> GameState:
        row = connection.execute(
            select(games.c.ruleset_id, games.c.host_id, games.c.player_ids).where(
                games.c.id == game_id
            )
        ).one_or_none()
        if row is None:
            raise GameNotFound(game_id)
        return new_game(
            game_id=game_id,
            ruleset=get_ruleset(row.ruleset_id),
            player_ids=row.player_ids,
            host_id=row.host_id,
        )

    def _events(self, connection: Connection, game_id: str) -> tuple[GameEvent, ...]:
        rows = connection.execute(
            select(game_events.c.type, game_events.c.payload)
            .where(game_events.c.game_id == game_id)
            .order_by(game_events.c.version)
        )
        return tuple(decode_event(row.type, row.payload) for row in rows)

    def _load(self, connection: Connection, game_id: str) -> GameState:
        return replay(self._initial(connection, game_id), self._events(connection, game_id))
