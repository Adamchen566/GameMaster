"""`TurnStore` on SQL."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select

from app.agents.turns import TurnRecord
from app.storage.database import Database
from app.storage.schema import agent_turns


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqlTurnStore:
    def __init__(self, database: Database, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._database = database
        self._now = now

    def add(self, game_id: str, record: TurnRecord) -> None:
        with self._database.transaction() as connection:
            # A turn replayed after a restart replaces the record it left before.
            connection.execute(
                delete(agent_turns).where(
                    agent_turns.c.game_id == game_id,
                    agent_turns.c.version == record.version,
                    agent_turns.c.player_id == record.player_id,
                )
            )
            connection.execute(
                insert(agent_turns).values(
                    game_id=game_id,
                    version=record.version,
                    player_id=record.player_id,
                    driver=record.driver,
                    source=record.source,
                    fallback_reason=record.fallback_reason,
                    attempts=record.attempts,
                    duration_ms=record.duration_ms,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    observation=dict(record.observation)
                    if record.observation is not None
                    else None,
                    exchanges=[dict(exchange) for exchange in record.exchanges],
                    created_at=self._now(),
                )
            )

    def for_game(self, game_id: str) -> tuple[TurnRecord, ...]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                select(agent_turns)
                .where(agent_turns.c.game_id == game_id)
                .order_by(agent_turns.c.version, agent_turns.c.player_id)
            )
            return tuple(
                TurnRecord(
                    version=row.version,
                    player_id=row.player_id,
                    driver=row.driver,
                    source=row.source,
                    fallback_reason=row.fallback_reason,
                    attempts=row.attempts,
                    duration_ms=row.duration_ms,
                    input_tokens=row.input_tokens,
                    output_tokens=row.output_tokens,
                    observation=row.observation,
                    exchanges=tuple(row.exchanges or ()),
                )
                for row in rows
            )
