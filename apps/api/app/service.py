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

from app.agents.drivers import Driver, default_driver
from app.agents.llm_player import AgentTurn, LlmPlayer, Style
from app.agents.model import TokenBudget, Usage
from app.agents.personas import BOT_NAMES, persona_for
from app.agents.state import AgentState, AgentStateStore, InMemoryAgentStateStore
from app.agents.table_bot import choose_action, inner_thought
from app.agents.thoughts import InMemoryThoughtStore, Thought, ThoughtStore, clean_thought
from app.agents.turns import InMemoryTurnStore, TurnRecord, TurnStore
from app.game.actions import Action, StartGame
from app.game.engine import apply_action, new_game
from app.game.errors import ErrorCode, RuleViolation
from app.game.events import GameEvent
from app.game.public_log import PublicEntry, public_log
from app.game.repository import GameRepository, InMemoryGameRepository, VersionConflict
from app.game.rulesets import OFFICIAL, RuleSet
from app.game.state import GameState, Phase
from app.game.views import PlayerView, build_player_view, build_spectator_view
from app.gm.narrator import Narration, Narrator
from app.gm.templates import Language
from app.observability import event_id, in_current_context
from app.rooms import (
    SPECTATOR_ID,
    InMemoryRoomStore,
    Room,
    RoomStore,
    Seat,
    hash_token,
    new_room_code,
    new_token,
)

log = logging.getLogger(__name__)

THOUGHTFUL = ("propose_team", "speak", "assassinate")
"""The turns a built-in bot leaves a thought for. A thought per ballot would be noise."""
ANNOUNCEMENT_LIMIT = 12
"""How many of the most recent public events a client is shown."""
UNMETERED_TOKENS = 10**15
"""The ceiling for local clients: a number no game reaches."""
MAX_AI_TURNS_PER_RUN = 500
"""A whole game is ~100 events; this only stops a bug from spinning forever."""


@dataclass(frozen=True, slots=True)
class Session:
    """An authenticated person: a seat at the table, or a spectator outside it."""

    room: Room
    seat: Seat

    @property
    def is_spectator(self) -> bool:
        return self.seat.player_id == SPECTATOR_ID


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
    spectator: bool = False
    """The client watches from outside the table and sees every role."""
    thoughts: tuple[Thought, ...] = ()
    """What the AI seats really thought. Empty for a player while the game is on."""


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
        drivers: Mapping[str, Driver] | None = None,
        thoughts: ThoughtStore | None = None,
        turns: TurnStore | None = None,
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
        self._drivers: Mapping[str, Driver] = drivers or {}
        # Players bound to one driver's model, made when a seat first needs one.
        self._driver_players: dict[tuple[str, str], LlmPlayer] = {}
        self._thoughts: ThoughtStore = thoughts if thoughts is not None else InMemoryThoughtStore()
        self._turns: TurnStore = turns if turns is not None else InMemoryTurnStore()
        self._narrator = narrator if narrator is not None else Narrator()
        self._budget = budget if budget is not None or not drivers else TokenBudget(300_000)
        # Local clients run on the person's subscription: counted, never cut off.
        self._unmetered = TokenBudget(UNMETERED_TOKENS)
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
        return bool(self._llm_players) or default_driver(self._drivers) is not None

    @property
    def gm_ai_available(self) -> bool:
        """Whether the game master can be voiced by a model here."""
        return self._narrator.has_model

    @property
    def drivers(self) -> Mapping[str, Driver]:
        """Every way of reaching a model this server knows, usable or not."""
        return self._drivers

    def turns(self, game_id: str) -> tuple[TurnRecord, ...]:
        """Every model turn of the game, for review. Holds secrets: not for players."""
        return self._turns.for_game(game_id)

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
        seats: Sequence[str] | None = None,
        spectate: bool = False,
    ) -> CreatedRoom:
        """Set up a table.

        `seats` says who plays each bot seat, in seat order: "bot" for the built-in
        bot or the id of a driver. Without it, the first `ai_seats` bot seats use the
        server's default model. With `spectate` nobody sits down: every seat is a bot
        and the person who made the room watches.
        """
        self._ruleset.for_players(player_count)
        bot_count = player_count if spectate else player_count - 1
        if seats is None:
            if not 0 <= ai_seats <= bot_count:
                raise ValueError("ai_seats must be between 0 and the number of bot seats.")
            seats = ["model"] * ai_seats + ["bot"] * (bot_count - ai_seats)
        if len(seats) != bot_count:
            raise ValueError(f"This table has {bot_count} bot seats, got {len(seats)} choices.")

        token, token_hash = new_token()
        first = 1 if spectate else 2
        bots = tuple(
            Seat(
                player_id=f"p{first + index}",
                name=BOT_NAMES[index],
                is_bot=True,
                agent="random" if choice == "bot" else "llm",
                style=None if choice == "bot" else ai_style,
                driver=None if choice in ("bot", "model") else choice,
            )
            for index, choice in enumerate(seats)
        )
        if spectate:
            person = Seat(
                player_id=SPECTATOR_ID, name=nickname, is_bot=False, token_hash=token_hash
            )
            table: tuple[Seat, ...] = bots
        else:
            person = Seat(player_id="p1", name=nickname, is_bot=False, token_hash=token_hash)
            table = (person, *bots)
        room = Room(
            code=new_room_code(),
            game_id=uuid4().hex,
            seed=self._new_seed(),
            seats=table,
            gm=gm,
            language=language,
            spectator=person if spectate else None,
        )
        state = new_game(
            game_id=room.game_id,
            ruleset=self._ruleset,
            player_ids=[seat.player_id for seat in room.seats],
            host_id=table[0].player_id,
        )

        # One transaction: a game without a room, or a room without a game, is never stored.
        with self._lock, self._transaction():
            self._games.create(state)
            self._rooms.add(room)

        session = Session(room=room, seat=person)
        return CreatedRoom(session=session, token=token, view=_view_of(session, state))

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
        return _view_of(session, state)

    def snapshot(self, session: Session) -> Snapshot:
        """The view plus what everyone at the table may see about the AI seats and the GM."""
        room = session.room
        with self._lock:
            state = self._games.load(room.game_id)
            events = self._games.events(room.game_id)
            agents = self._agent_states.for_game(room.game_id)
            # A thought usually gives a seat's side away: only for those who may know it.
            open_book = session.is_spectator or state.phase is Phase.FINISHED
            thoughts = self._thoughts.for_game(room.game_id) if open_book else ()

        thinking = tuple(
            seat.player_id
            for seat in room.seats
            if seat.is_bot and build_player_view(state, seat.player_id).legal_actions
        )
        return Snapshot(
            view=_view_of(session, state),
            thinking=thinking,
            agents=agents,
            announcements=self._announcements(room, events),
            log=public_log(events),
            usage=self._budget.usage(room.game_id) if self._budget else Usage(),
            cost_usd=self._budget.cost(room.game_id) if self._budget else None,
            spectator=session.is_spectator,
            thoughts=thoughts,
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
            if session.is_spectator:
                # Watching is all a spectator does, except opening the game they set up.
                if not isinstance(action, StartGame):
                    raise RuleViolation(
                        ErrorCode.UNKNOWN_PLAYER, "A spectator has no seat at this table."
                    )
                action = replace(action, player_id=state.host_id)

            earlier = self._games.events(room.game_id)
            state, events = apply_action(state, action)
            state, bot_events, thoughts = self._play_bot_turns(room, state, [*earlier, *events])

            new_events = [*events, *bot_events]
            self._games.append(room.game_id, loaded_version, new_events)
            self._thoughts.add(room.game_id, tuple(thoughts))

        _log_events(room.game_id, loaded_version, new_events, actor=session.seat.player_id)
        self._after_append(room, state, loaded_version, new_events)
        return _view_of(session, state)

    def _play_bot_turns(
        self, room: Room, state: GameState, so_far: Sequence[GameEvent]
    ) -> tuple[GameState, list[GameEvent], list[Thought]]:
        """Let the built-in bots act until a human or a model seat is due."""
        events: list[GameEvent] = []
        thoughts: list[Thought] = []
        names, language = _names(room), _language(room)
        bots = [seat for seat in room.seats if _agent(seat) == "random"]

        while True:
            for bot in bots:
                view = build_player_view(state, bot.player_id)
                if view.legal_actions:
                    history = public_log([*so_far, *events])
                    thought = _bot_thought(room, view, history)
                    if thought:
                        thoughts.append(Thought(state.version + 1, bot.player_id, thought))
                    action = choose_action(
                        view,
                        _rng(room, view),
                        history=history,
                        names=names,
                        language=language,
                        salt=str(room.seed),
                    )
                    state, new_events = apply_action(state, action)
                    events.extend(new_events)
                    break
            else:
                return state, events, thoughts

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
        action, after, thought, turn = self._decide(room, seat, view, history, before)
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
            if thought:
                self._thoughts.add(game_id, (Thought(fresh.version + 1, seat.player_id, thought),))
            if _agent(seat) == "llm" and after is not None:
                record = _turn_record(fresh.version + 1, seat, after, turn, decided_ms)
                self._turns.add(game_id, record)

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
    ) -> tuple[Action, AgentState | None, str, AgentTurn | None]:
        """The seat's action, its new private state (model seats) and what it thought."""
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
            return bot, None, _bot_thought(room, view, history), None

        player = self._player_for(seat)
        if player is None:
            # The room was created with model seats, but this server cannot reach the model now.
            unavailable = replace(
                before, last_source="fallback", last_fallback_reason="unavailable"
            )
            return bot, unavailable, _bot_thought(room, view, history), None

        persona = persona_for(seat.name)
        turn = player.take_turn(
            view,
            names=_names(room),
            history=history,
            note=before.note,
            rng=rng,
            persona=persona.manner_en if persona is not None else None,
        )
        after = AgentState(
            # A fallback turn has no new note; keep what the seat knew before.
            note=turn.note if turn.note is not None else before.note,
            last_source=turn.source,
            last_fallback_reason=turn.fallback_reason,
        )
        return turn.action, after, clean_thought(turn.inner or ""), turn

    def _player_for(self, seat: Seat) -> LlmPlayer | None:
        """The model player for this seat, or None when its model cannot be reached."""
        style: Style = "baseline"
        if seat.style == "cautious":
            style = "cautious"
        elif seat.style == "aggressive":
            style = "aggressive"
        if seat.driver is None:
            return self._llm_players.get(style)
        driver = self._drivers.get(seat.driver)
        if driver is None or driver.model is None:
            return None
        budget = self._budget if driver.metered else self._unmetered
        if budget is None:
            return None
        key = (driver.id, style)
        if key not in self._driver_players:
            self._driver_players[key] = LlmPlayer(
                driver.model, budget, style=style, timeout_seconds=driver.timeout_seconds
            )
        return self._driver_players[key]


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


def _turn_record(
    version: int, seat: Seat, after: AgentState, turn: AgentTurn | None, duration_ms: float
) -> TurnRecord:
    """What to keep of one model-driven turn. `turn` is None when no model could be asked."""
    return TurnRecord(
        version=version,
        player_id=seat.player_id,
        driver=seat.driver or "default",
        source=after.last_source or "fallback",
        fallback_reason=after.last_fallback_reason,
        attempts=turn.attempts if turn is not None else 0,
        duration_ms=duration_ms,
        input_tokens=turn.input_tokens if turn is not None else 0,
        output_tokens=turn.output_tokens if turn is not None else 0,
        observation=turn.observation if turn is not None else None,
        exchanges=turn.exchanges if turn is not None else (),
    )


def _view_of(session: Session, state: GameState) -> PlayerView:
    if session.is_spectator:
        return build_spectator_view(state)
    return build_player_view(state, session.seat.player_id)


def _bot_thought(room: Room, view: PlayerView, history: Sequence[PublicEntry]) -> str:
    """What the built-in bot in this seat believes, for the turns worth a thought."""
    if not view.legal_actions or view.legal_actions[0].type not in THOUGHTFUL:
        return ""
    return clean_thought(
        inner_thought(
            view,
            history=history,
            names=_names(room),
            language=_language(room),
            salt=str(room.seed),
        )
    )


def _names(room: Room) -> dict[str, str]:
    return {seat.player_id: seat.name for seat in room.seats}


def _language(room: Room) -> Language:
    return "en" if room.language == "en" else "zh"


def _rng(room: Room, view: PlayerView) -> random.Random:
    # Seeded from stable facts so a game can be reproduced from its seed.
    return random.Random(f"{room.seed}:{view.you_id}:{view.version}")
