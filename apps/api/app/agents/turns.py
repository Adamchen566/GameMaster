"""The full record of every turn a model-driven seat played.

The event log says what a seat did. This says how it got there: exactly what
the model was shown, every answer it gave (including the ones the game turned
down), which model it was, how long it took and what it cost. Together with
the event log it is enough to replay and audit a game later.

Like a role, a turn record is secret while the game is on: the observation
holds the seat's role and private notes. It is only read back for review.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class TurnRecord:
    version: int
    """Version of the game after the first event of the action this turn produced."""
    player_id: str
    driver: str
    """"claude", "deepseek", "claude_code", "codex", or "default" for the server's default model."""
    source: str
    """"model" or "fallback"."""
    fallback_reason: str | None
    attempts: int
    duration_ms: float
    input_tokens: int
    output_tokens: int
    observation: Mapping[str, Any] | None
    """Exactly what the model was sent; None when no model was asked."""
    exchanges: tuple[Mapping[str, Any], ...] = field(default=())
    """One entry per model call: the answer, why the game turned it down, or the error."""


class TurnStore(Protocol):
    def add(self, game_id: str, record: TurnRecord) -> None:
        """Remember one turn."""

    def for_game(self, game_id: str) -> tuple[TurnRecord, ...]:
        """Every recorded turn of the game, oldest first."""


class InMemoryTurnStore:
    def __init__(self) -> None:
        self._turns: dict[str, list[TurnRecord]] = {}

    def add(self, game_id: str, record: TurnRecord) -> None:
        self._turns.setdefault(game_id, []).append(record)

    def for_game(self, game_id: str) -> tuple[TurnRecord, ...]:
        return tuple(sorted(self._turns.get(game_id, ()), key=lambda record: record.version))
