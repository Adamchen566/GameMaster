"""`AgentStateStore` on SQL."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select

from app.agents.state import AgentState
from app.storage.database import Database
from app.storage.schema import agent_states


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqlAgentStateStore:
    def __init__(self, database: Database, *, now: Callable[[], datetime] = _utc_now) -> None:
        self._database = database
        self._now = now

    def get(self, game_id: str, player_id: str) -> AgentState:
        return self.for_game(game_id).get(player_id, AgentState())

    def put(self, game_id: str, player_id: str, state: AgentState) -> None:
        # Delete-then-insert in one transaction: portable, and one writer per
        # game is guaranteed by the caller.
        with self._database.transaction() as connection:
            connection.execute(
                delete(agent_states).where(
                    agent_states.c.game_id == game_id, agent_states.c.player_id == player_id
                )
            )
            connection.execute(
                insert(agent_states).values(
                    game_id=game_id,
                    player_id=player_id,
                    note=state.note,
                    last_source=state.last_source,
                    last_fallback_reason=state.last_fallback_reason,
                    updated_at=self._now(),
                )
            )

    def for_game(self, game_id: str) -> dict[str, AgentState]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                select(
                    agent_states.c.player_id,
                    agent_states.c.note,
                    agent_states.c.last_source,
                    agent_states.c.last_fallback_reason,
                ).where(agent_states.c.game_id == game_id)
            )
            return {
                row.player_id: AgentState(
                    note=row.note,
                    last_source=row.last_source,
                    last_fallback_reason=row.last_fallback_reason,
                )
                for row in rows
            }
