"""Where games are stored: an append-only event log per game.

The interface is what the rest of the app depends on. `InMemoryGameRepository`
keeps everything in a dict and is lost on restart; v0.4 adds a PostgreSQL
implementation with the same methods.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.game.engine import replay
from app.game.events import GameEvent
from app.game.state import GameState


class GameNotFound(Exception):
    def __init__(self, game_id: str) -> None:
        super().__init__(f"Game '{game_id}' does not exist.")
        self.game_id = game_id


class VersionConflict(Exception):
    """Someone else appended events since the caller loaded the game."""

    def __init__(self, game_id: str, expected: int, actual: int) -> None:
        super().__init__(
            f"Game '{game_id}' is at version {actual}, but the caller expected {expected}."
        )
        self.game_id = game_id
        self.expected = expected
        self.actual = actual


class GameRepository(Protocol):
    def create(self, initial: GameState) -> None:
        """Store a new game in its lobby state."""

    def load(self, game_id: str) -> GameState:
        """Return the current state, rebuilt from the stored events."""

    def events(self, game_id: str) -> tuple[GameEvent, ...]:
        """Return every stored event in order."""

    def append(self, game_id: str, expected_version: int, events: Sequence[GameEvent]) -> GameState:
        """Add events if the game is still at `expected_version`, else raise VersionConflict."""


@dataclass(slots=True)
class _StoredGame:
    current: GameState
    events: list[GameEvent] = field(default_factory=list)


class InMemoryGameRepository:
    def __init__(self) -> None:
        self._games: dict[str, _StoredGame] = {}

    def create(self, initial: GameState) -> None:
        if initial.game_id in self._games:
            raise ValueError(f"Game '{initial.game_id}' already exists.")
        if initial.version != 0:
            raise ValueError("A new game must be stored before any event is applied.")
        self._games[initial.game_id] = _StoredGame(current=initial)

    def load(self, game_id: str) -> GameState:
        return self._stored(game_id).current

    def events(self, game_id: str) -> tuple[GameEvent, ...]:
        return tuple(self._stored(game_id).events)

    def append(self, game_id: str, expected_version: int, events: Sequence[GameEvent]) -> GameState:
        stored = self._stored(game_id)
        if stored.current.version != expected_version:
            raise VersionConflict(game_id, expected_version, stored.current.version)

        stored.current = replay(stored.current, events)
        stored.events.extend(events)
        return stored.current

    def _stored(self, game_id: str) -> _StoredGame:
        stored = self._games.get(game_id)
        if stored is None:
            raise GameNotFound(game_id)
        return stored
