"""`ThoughtStore` on SQL."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select

from app.agents.thoughts import Thought
from app.storage.database import Database
from app.storage.schema import agent_thoughts


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqlThoughtStore:
    def __init__(self, database: Database, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._database = database
        self._now = now

    def add(self, game_id: str, thoughts: tuple[Thought, ...]) -> None:
        if not thoughts:
            return
        with self._database.transaction() as connection:
            for thought in thoughts:
                # A turn that is replayed after a restart writes its thought again.
                connection.execute(
                    delete(agent_thoughts).where(
                        agent_thoughts.c.game_id == game_id,
                        agent_thoughts.c.version == thought.version,
                        agent_thoughts.c.player_id == thought.player_id,
                    )
                )
            connection.execute(
                insert(agent_thoughts),
                [
                    {
                        "game_id": game_id,
                        "version": thought.version,
                        "player_id": thought.player_id,
                        "text": thought.text,
                        "created_at": self._now(),
                    }
                    for thought in thoughts
                ],
            )

    def for_game(self, game_id: str) -> tuple[Thought, ...]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                select(
                    agent_thoughts.c.version,
                    agent_thoughts.c.player_id,
                    agent_thoughts.c.text,
                )
                .where(agent_thoughts.c.game_id == game_id)
                .order_by(agent_thoughts.c.version, agent_thoughts.c.player_id)
            )
            return tuple(
                Thought(version=row.version, player_id=row.player_id, text=row.text) for row in rows
            )
