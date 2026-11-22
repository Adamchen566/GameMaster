"""What an AI seat keeps between turns.

`note` is the model's private reminder to itself and is as secret as a role:
it is given back only to the same seat's next turn and never to a client.
The outcome of the last turn (model or fallback, and why) is public status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AgentState:
    note: str = ""
    last_source: str | None = None
    """"model" or "fallback"; None before the seat's first turn."""
    last_fallback_reason: str | None = None


class AgentStateStore(Protocol):
    def get(self, game_id: str, player_id: str) -> AgentState:
        """Return the seat's state; an empty state if it has not played yet."""

    def put(self, game_id: str, player_id: str, state: AgentState) -> None:
        """Replace the seat's state."""

    def for_game(self, game_id: str) -> dict[str, AgentState]:
        """Return the state of every seat that has one, keyed by player id."""


class InMemoryAgentStateStore:
    def __init__(self) -> None:
        self._states: dict[tuple[str, str], AgentState] = {}

    def get(self, game_id: str, player_id: str) -> AgentState:
        return self._states.get((game_id, player_id), AgentState())

    def put(self, game_id: str, player_id: str, state: AgentState) -> None:
        self._states[(game_id, player_id)] = state

    def for_game(self, game_id: str) -> dict[str, AgentState]:
        return {
            player_id: state
            for (stored_game_id, player_id), state in self._states.items()
            if stored_game_id == game_id
        }
