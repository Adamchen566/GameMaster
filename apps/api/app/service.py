"""Application service: rooms, the command path, bot turns and AI turns.

Humans, bots and models go through the same path: an action is checked by
`apply_action`, and only then are its events appended to the repository.

Random bots are instant, so they play inside the human's request. A model can
take seconds, so seats played by a model act on a background executor: the
request returns as soon as it is a model's turn, and clients poll the game to
see the turn arrive.
"""

from __future__ import annotations

import logging
import random
import secrets
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import uuid4

from app.agents.llm_player import LlmPlayer
from app.agents.model import TokenBudget, Usage
from app.agents.state import AgentState, AgentStateStore, InMemoryAgentStateStore
from app.agents.table_bot import choose_action
from app.game.actions import Action
from app.game.engine import apply_action, new_game
from app.game.errors import RuleViolation
from app.game.events import GameEvent
from app.game.public_log import PublicEntry, public_log
from app.game.repository import GameRepository, InMemoryGameRepository, VersionConflict
from app.game.rulesets import OFFICIAL, RuleSet
from app.game.state import GameState
from app.game.views import PlayerView, build_player_view
from app.gm.narrator import Narration, Narrator
from app.gm.templates import Language
from app.observability import event_id, in_current_context
from app.rooms import (
    InMemoryRoomStore,
    Room,
    RoomStore,
    Seat,
    hash_token,
    new_room_code,
    new_token,
)

log = logging.getLogger(__name__)

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

ANNOUNCEMENT_LIMIT = 12
"""How many of the most recent public events a client is shown."""
MAX_AI_TURNS_PER_RUN = 500
"""A whole game is ~100 events; this only stops a bug from spinning forever."""


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


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything one client is shown: its view plus public table status."""

    view: PlayerView
    thinking: tuple[str, ...]
    """AI seats the game is waiting on right now."""
    agents: Mapping[str, AgentState]
    """Only `last_source` and `last_fallback_reason` may be shown; `note` is private."""
    announcements: tuple[Narration, ...]
    log: tuple[PublicEntry, ...]
    """Everything that has happened in the open, oldest first. The client replays it step by step."""
    usage: Usage
    cost_usd: float | None


class Executor(Protocol):
    def submit(self, task: Callable[[], None]) -> object:
        """Run `task` later, on another thread."""


class InlineExecutor:
    """Runs tasks at once on the calling thread. For tests and scripts."""

    def submit(self, task: Callable[[], None]) -> object:
        task()
        return None


class _ThreadExecutor:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-turn")

    def submit(self, task: Callable[[], None]) -> object:
        return self._pool.submit(task)


def _random_seed() -> int:
    return secrets.randbits(63)


def _agent(seat: Seat) -> str | None:
    """Return "random" or "llm" for a bot seat, None for a human.

    Bot seats stored before AI seats existed have no agent; they are random bots.
    """
    return (seat.agent or "random") if seat.is_bot else None


class GameService:
    def __init__(
        self,
        games: GameRepository | None = None,
        rooms: RoomStore | None = None,
        *,
        transaction: Callable[[], AbstractContextManager[object]] = nullcontext,
        ruleset: RuleSet = OFFICIAL,
        new_seed: Callable[[], int] = _random_seed,
        agent_states: AgentStateStore | None = None,
        llm_players: Mapping[str, LlmPlayer] | None = None,
        narrator: Narrator | None = None,
        budget: TokenBudget | None = None,
        executor: Executor | None = None,
    ) -> None:
        self._games: GameRepository = games if games is not None else InMemoryGameRepository()
        self._rooms: RoomStore = rooms if rooms is not None else InMemoryRoomStore()
        # With a database, everything inside one `with self._transaction()` commits together.
        self._transaction = transaction
        self._ruleset = ruleset
        self._new_seed = new_seed
        self._agent_states: AgentStateStore = (
            agent_states if agent_states is not None else InMemoryAgentStateStore()
        )
        self._llm_players: Mapping[str, LlmPlayer] = llm_players or {}
        self._narrator = narrator if narrator is not None else Narrator()
        self._budget = budget
        self._executor: Executor = executor if executor is not None else _ThreadExecutor()
        # Serialises writers inside this process. Across processes the repository's
        # version check decides who wins. Never held while a model is being called.
        self._lock = threading.Lock()
        # Games that currently have a background run playing their AI turns.
        self._running: set[str] = set()
        self._running_lock = threading.Lock()

    @property
    def llm_available(self) -> bool:
        """Whether seats and the game master can be played by a model on this server."""
        return bool(self._llm_players)

    # --- Rooms -----------------------------------------------------------------

    def create_room(
        self,
        nickname: str,
        player_count: int,
        *,
        ai_seats: int = 0,
        ai_style: str = "baseline",
        gm: str = "template",
        language: str = "zh",
    ) -> CreatedRoom:
        """Seat one human as host; fill the rest with `ai_seats` model seats, then random bots."""
        self._ruleset.for_players(player_count)
        if not 0 <= ai_seats <= player_count - 1:
            raise ValueError("ai_seats must be between 0 and the number of bot seats.")

        token, token_hash = new_token()
        human = Seat(player_id="p1", name=nickname, is_bot=False, token_hash=token_hash)
        bots = tuple(
            Seat(
                player_id=f"p{number}",
                name=BOT_NAMES[number - 2],
                is_bot=True,
                agent="llm" if number - 2 < ai_seats else "random",
                style=ai_style if number - 2 < ai_seats else None,
            )
            for number in range(2, player_count + 1)
        )
        room = Room(
            code=new_room_code(),
            game_id=uuid4().hex,
            seed=self._new_seed(),
            seats=(human, *bots),
            gm=gm,
            language=language,
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

    # --- Reading ---------------------------------------------------------------

    def view(self, session: Session) -> PlayerView:
        with self._lock:
            state = self._games.load(session.room.game_id)
        # Self-healing: if the server restarted while a model was due to act,
        # the next poll starts its turn again.
        self._ensure_ai_running(session.room, state)
        return build_player_view(state, session.seat.player_id)

    def snapshot(self, session: Session) -> Snapshot:
        """The view plus what everyone at the table may see about the AI seats and the GM."""
        room = session.room
        with self._lock:
            state = self._games.load(room.game_id)
            events = self._games.events(room.game_id)
            agents = self._agent_states.for_game(room.game_id)

        thinking = tuple(
            seat.player_id
            for seat in room.seats
            if seat.is_bot and build_player_view(state, seat.player_id).legal_actions
        )
        return Snapshot(
            view=build_player_view(state, session.seat.player_id),
            thinking=thinking,
            agents=agents,
            announcements=self._announcements(room, events),
            log=public_log(events),
            usage=self._budget.usage(room.game_id) if self._budget else Usage(),
            cost_usd=self._budget.cost(room.game_id) if self._budget else None,
        )

    def _announcements(self, room: Room, events: Sequence[GameEvent]) -> tuple[Narration, ...]:
        if room.gm == "off":
            return ()
        names = _names(room)
        language = _language(room)
        return tuple(
            self._narrator.peek(room.game_id, entry, names, language)
            for entry in _narrated(public_log(events))[-ANNOUNCEMENT_LIMIT:]
        )

    # --- Writing ---------------------------------------------------------------

    def submit(self, session: Session, action: Action) -> PlayerView:
        """Apply a human action, let the instant bots answer, and hand over to any model seat."""
        room = session.room
        with self._lock:
            state = self._games.load(room.game_id)
            loaded_version = state.version

            earlier = self._games.events(room.game_id)
            state, events = apply_action(state, action)
            state, bot_events = self._play_bot_turns(room, state, [*earlier, *events])

            new_events = [*events, *bot_events]
            self._games.append(room.game_id, loaded_version, new_events)

        _log_events(room.game_id, loaded_version, new_events, actor=session.seat.player_id)
        self._after_append(room, state, loaded_version, new_events)
        return build_player_view(state, session.seat.player_id)

    def _play_bot_turns(
        self, room: Room, state: GameState, so_far: Sequence[GameEvent]
    ) -> tuple[GameState, list[GameEvent]]:
        """Let the built-in bots act until a human or a model seat is due."""
        events: list[GameEvent] = []
        names, language = _names(room), _language(room)
        bots = [seat for seat in room.seats if _agent(seat) == "random"]

        while True:
            for bot in bots:
                view = build_player_view(state, bot.player_id)
                if view.legal_actions:
                    action = choose_action(
                        view,
                        _rng(room, view),
                        history=public_log([*so_far, *events]),
                        names=names,
                        language=language,
                        salt=str(room.seed),
                    )
                    state, new_events = apply_action(state, action)
                    events.extend(new_events)
                    break
            else:
                return state, events

    def _after_append(
        self, room: Room, state: GameState, first_version: int, events: Sequence[GameEvent]
    ) -> None:
        """Start whatever the new events call for. Must be called without the lock held."""
        if room.gm == "ai" and self._narrator.has_model:
            entries = _narrated(public_log(events, first_version=first_version + 1))
            if entries:
                names, language = _names(room), _language(room)

                def narrate() -> None:
                    for entry in entries:
                        self._narrator.narrate(room.game_id, entry, names, language)

                self._executor.submit(in_current_context(narrate))
        self._ensure_ai_running(room, state)

    # --- AI turns --------------------------------------------------------------

    def _ai_actor(self, room: Room, state: GameState) -> Seat | None:
        """The AI seat to move next: instant bots before models."""
        waiting = [
            seat
            for seat in room.seats
            if seat.is_bot and build_player_view(state, seat.player_id).legal_actions
        ]
        waiting.sort(key=lambda seat: _agent(seat) != "random")
        return waiting[0] if waiting else None

    def _ensure_ai_running(self, room: Room, state: GameState) -> None:
        if self._ai_actor(room, state) is None:
            return
        with self._running_lock:
            if room.game_id in self._running:
                return
            self._running.add(room.game_id)
        self._executor.submit(in_current_context(lambda: self._run_ai_turns(room)))

    def _run_ai_turns(self, room: Room) -> None:
        try:
            for _ in range(MAX_AI_TURNS_PER_RUN):
                if not self._play_one_ai_turn(room):
                    return
            log.error("ai_turns_did_not_settle", extra={"game_id": room.game_id})
        except Exception:
            # Nothing may be raised into the executor; the next poll starts a new run.
            log.exception("ai_turn_failed", extra={"game_id": room.game_id})
        finally:
            with self._running_lock:
                self._running.discard(room.game_id)

    def _play_one_ai_turn(self, room: Room) -> bool:
        """Play one AI action. False when no AI seat has anything to do."""
        game_id = room.game_id
        with self._lock:
            state = self._games.load(game_id)
            seat = self._ai_actor(room, state)
            if seat is None:
                return False
            history = public_log(self._games.events(game_id))
            before = self._agent_states.get(game_id, seat.player_id)

        view = build_player_view(state, seat.player_id)
        # The slow part. No lock is held, so people can keep acting meanwhile.
        started = time.perf_counter()
        action, after = self._decide(room, seat, view, history, before)
        decided_ms = round((time.perf_counter() - started) * 1000, 1)

        with self._lock, self._transaction():
            fresh = self._games.load(game_id)
            if fresh.version != state.version:
                # The table moved while the seat was thinking. Its decision still
                # stands if it faces the same choice; otherwise it decides again.
                now = build_player_view(fresh, seat.player_id)
                if now.legal_actions != view.legal_actions:
                    return True
                action = replace(action, expected_version=fresh.version)
            try:
                new_state, events = apply_action(fresh, action)
                self._games.append(game_id, fresh.version, events)
            except (RuleViolation, VersionConflict):
                return True
            if after is not None:
                self._agent_states.put(game_id, seat.player_id, after)

        log.info(
            "ai_turn",
            extra={
                "game_id": game_id,
                "event_id": event_id(game_id, new_state.version),
                "player_id": seat.player_id,
                "agent": _agent(seat),
                "source": after.last_source if after is not None else "random",
                "fallback_reason": after.last_fallback_reason if after is not None else None,
                "duration_ms": decided_ms,
            },
        )
        _log_events(game_id, fresh.version, events, actor=seat.player_id)
        self._after_append(room, new_state, fresh.version, events)
        return True

    def _decide(
        self,
        room: Room,
        seat: Seat,
        view: PlayerView,
        history: Sequence[PublicEntry],
        before: AgentState,
    ) -> tuple[Action, AgentState | None]:
        rng = _rng(room, view)
        bot = choose_action(
            view,
            rng,
            history=history,
            names=_names(room),
            language=_language(room),
            salt=str(room.seed),
        )
        if _agent(seat) != "llm":
            return bot, None

        player = self._llm_players.get(seat.style or "baseline")
        if player is None:
            # The room was created with model seats, but this server has no model now.
            return bot, replace(before, last_source="fallback", last_fallback_reason="unavailable")

        turn = player.take_turn(
            view, names=_names(room), history=history, note=before.note, rng=rng
        )
        return turn.action, AgentState(
            # A fallback turn has no new note; keep what the seat knew before.
            note=turn.note if turn.note is not None else before.note,
            last_source=turn.source,
            last_fallback_reason=turn.fallback_reason,
        )


def _log_events(
    game_id: str, version_before: int, events: Sequence[GameEvent], *, actor: str
) -> None:
    """One line per batch of appended events. Type names only: payloads hold secrets."""
    version = version_before + len(events)
    log.info(
        "events_appended",
        extra={
            "game_id": game_id,
            "event_id": event_id(game_id, version),
            "version": version,
            "actor": actor,
            "events": [type(event).__name__ for event in events],
        },
    )


def _narrated(entries: Sequence[PublicEntry]) -> tuple[PublicEntry, ...]:
    """The game master announces what happened, not what people said."""
    return tuple(entry for entry in entries if entry.kind != "speech")


def _names(room: Room) -> dict[str, str]:
    return {seat.player_id: seat.name for seat in room.seats}


def _language(room: Room) -> Language:
    return "en" if room.language == "en" else "zh"


def _rng(room: Room, view: PlayerView) -> random.Random:
    # Seeded from stable facts so a game can be reproduced from its seed.
    return random.Random(f"{room.seed}:{view.you_id}:{view.version}")
