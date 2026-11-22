"""Application service: rooms, the command path and bot turns.

Humans and bots go through the same path: an action is checked by
`apply_action`, and only then are its events appended to the repository.
"""

from __future__ import annotations

import random
import secrets
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from uuid import uuid4

from app.agents.policy_fallback import choose_action
from app.game.actions import Action
from app.game.engine import apply_action, new_game
from app.game.events import GameEvent
from app.game.repository import GameRepository, InMemoryGameRepository
from app.game.rulesets import OFFICIAL, RuleSet
from app.game.state import GameState
from app.game.views import PlayerView, build_player_view
from app.rooms import (
    InMemoryRoomStore,
    Room,
    RoomStore,
    Seat,
    hash_token,
    new_room_code,
    new_token,
)

BOT_NAMES = (
    "Gawain",
    "Lancelot",
    "Tristan",
    "Galahad",
    "Bors",
    "Kay",
    "Bedivere",
    "Gareth",
    "Lamorak",
)


@dataclass(frozen=True, slots=True)
class Session:
    """An authenticated human seat."""

    room: Room
    seat: Seat


@dataclass(frozen=True, slots=True)
class CreatedRoom:
    session: Session
    token: str
    """Returned to the client once and never stored."""
    view: PlayerView


def _random_seed() -> int:
    return secrets.randbits(63)


class GameService:
    def __init__(
        self,
        games: GameRepository | None = None,
        rooms: RoomStore | None = None,
        *,
        transaction: Callable[[], AbstractContextManager[object]] = nullcontext,
        ruleset: RuleSet = OFFICIAL,
        new_seed: Callable[[], int] = _random_seed,
    ) -> None:
        self._games: GameRepository = games if games is not None else InMemoryGameRepository()
        self._rooms: RoomStore = rooms if rooms is not None else InMemoryRoomStore()
        # With a database, everything inside one `with self._transaction()` commits together.
        self._transaction = transaction
        self._ruleset = ruleset
        self._new_seed = new_seed
        # Serialises writers inside this process. Across processes the repository's
        # version check decides who wins.
        self._lock = threading.Lock()

    def create_room(self, nickname: str, player_count: int) -> CreatedRoom:
        """Seat one human as host and fill the remaining seats with bots."""
        self._ruleset.for_players(player_count)

        token, token_hash = new_token()
        human = Seat(player_id="p1", name=nickname, is_bot=False, token_hash=token_hash)
        bots = tuple(
            Seat(player_id=f"p{number}", name=BOT_NAMES[number - 2], is_bot=True)
            for number in range(2, player_count + 1)
        )
        room = Room(
            code=new_room_code(),
            game_id=uuid4().hex,
            seed=self._new_seed(),
            seats=(human, *bots),
        )
        state = new_game(
            game_id=room.game_id,
            ruleset=self._ruleset,
            player_ids=[seat.player_id for seat in room.seats],
            host_id=human.player_id,
        )

        # One transaction: a game without a room, or a room without a game, is never stored.
        with self._lock, self._transaction():
            self._games.create(state)
            self._rooms.add(room)

        session = Session(room=room, seat=human)
        return CreatedRoom(
            session=session, token=token, view=build_player_view(state, human.player_id)
        )

    def authenticate(self, token: str) -> Session | None:
        found = self._rooms.by_token_hash(hash_token(token))
        if found is None:
            return None
        room, seat = found
        return Session(room=room, seat=seat)

    def find_room(self, game_id: str) -> Room | None:
        return self._rooms.by_game_id(game_id)

    def view(self, session: Session) -> PlayerView:
        with self._lock:
            state = self._games.load(session.room.game_id)
        return build_player_view(state, session.seat.player_id)

    def submit(self, session: Session, action: Action) -> PlayerView:
        """Apply a human action, then let the bots play until a human is needed again."""
        room = session.room
        with self._lock:
            state = self._games.load(room.game_id)
            loaded_version = state.version

            state, events = apply_action(state, action)
            state, bot_events = self._play_bot_turns(room, state)

            self._games.append(room.game_id, loaded_version, [*events, *bot_events])
        return build_player_view(state, session.seat.player_id)

    def _play_bot_turns(self, room: Room, state: GameState) -> tuple[GameState, list[GameEvent]]:
        events: list[GameEvent] = []
        bots = [seat for seat in room.seats if seat.is_bot]

        while True:
            for bot in bots:
                view = build_player_view(state, bot.player_id)
                if view.legal_actions:
                    # Seeded from stable facts so a game can be reproduced from its seed.
                    rng = random.Random(f"{room.seed}:{bot.player_id}:{state.version}")
                    state, new_events = apply_action(state, choose_action(view, rng))
                    events.extend(new_events)
                    break
            else:
                return state, events
