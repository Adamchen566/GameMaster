"""Rooms: who sits in which seat of a game, and how humans prove it.

A room is the application-level wrapper around one game. The rules engine only
knows player ids; names, bot seats and reconnect tokens live here. Storage is
in memory for now and moves to PostgreSQL in v0.4.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Seat:
    player_id: str
    name: str
    is_bot: bool
    token_hash: str | None = None
    """SHA-256 of the reconnect token. The token itself is never stored."""


@dataclass(frozen=True, slots=True)
class Room:
    code: str
    game_id: str
    seed: int
    """Chosen by the server; drives the deal and the bots, and is never sent to clients."""
    seats: tuple[Seat, ...]


def new_token() -> tuple[str, str]:
    """Return a fresh reconnect token and the digest to store for it."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    # The token is 256 bits of randomness, so a plain fast hash is enough:
    # there is nothing for an attacker to guess or brute-force.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I


def new_room_code() -> str:
    return "".join(secrets.choice(_ROOM_CODE_ALPHABET) for _ in range(6))


class InMemoryRoomStore:
    def __init__(self) -> None:
        self._by_game_id: dict[str, Room] = {}
        self._by_token_hash: dict[str, tuple[Room, Seat]] = {}

    def add(self, room: Room) -> None:
        self._by_game_id[room.game_id] = room
        for seat in room.seats:
            if seat.token_hash is not None:
                self._by_token_hash[seat.token_hash] = (room, seat)

    def by_game_id(self, game_id: str) -> Room | None:
        return self._by_game_id.get(game_id)

    def by_token_hash(self, token_hash: str) -> tuple[Room, Seat] | None:
        return self._by_token_hash.get(token_hash)
