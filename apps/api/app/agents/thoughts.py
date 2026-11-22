"""What an AI seat was really thinking when it acted.

A thought is as secret as a role while the game is on: it usually says which
side the seat is on. It is shown to someone watching from outside the table,
and to everyone once the game is over, so a game can be reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

THOUGHT_LIMIT = 160
"""Characters kept of one thought."""


@dataclass(frozen=True, slots=True)
class Thought:
    version: int
    """Version of the game after the first event of the action the thought belongs to."""
    player_id: str
    text: str


def clean_thought(text: str) -> str:
    single_line = " ".join(text.split())
    return "".join(ch for ch in single_line if ch.isprintable())[:THOUGHT_LIMIT]


class ThoughtStore(Protocol):
    def add(self, game_id: str, thoughts: tuple[Thought, ...]) -> None:
        """Remember these thoughts."""

    def for_game(self, game_id: str) -> tuple[Thought, ...]:
        """Every thought of the game, oldest first."""


class InMemoryThoughtStore:
    def __init__(self) -> None:
        self._thoughts: dict[str, list[Thought]] = {}

    def add(self, game_id: str, thoughts: tuple[Thought, ...]) -> None:
        self._thoughts.setdefault(game_id, []).extend(thoughts)

    def for_game(self, game_id: str) -> tuple[Thought, ...]:
        return tuple(sorted(self._thoughts.get(game_id, ()), key=lambda thought: thought.version))
