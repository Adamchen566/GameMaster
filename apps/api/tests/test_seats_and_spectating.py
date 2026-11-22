"""A model per seat, personas, inner thoughts, and watching a table from outside."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.drivers import Driver
from app.agents.model import ModelReply, ModelUnavailable, TokenBudget
from app.agents.personas import BOT_NAMES, PERSONAS, persona_for
from app.agents.table_bot import choose_action as bot_action
from app.api.deps import get_service
from app.game.actions import Speak, StartGame, VoteTeam
from app.game.errors import RuleViolation
from app.game.rulesets import Role
from app.game.state import Phase
from app.main import app
from app.rooms import SPECTATOR_ID
from app.service import CreatedRoom, GameService, InlineExecutor
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from app.storage.rooms import SqlRoomStore
from app.storage.thoughts import SqlThoughtStore
from tests.storage.conftest import SQL_BACKENDS, database_url

ROLE_WORDS = ("邪恶方", "evil", "梅林", "Merlin")


class NamedModel:
    """A model that plays a legal move and signs everything it says with its own name."""

    def __init__(self, name: str, *, fail: Exception | None = None) -> None:
        self.name, self.fail = name, fail
        self.systems: list[str] = []

    def complete(
        self, *, system: str, user: str, schema: Mapping[str, Any], timeout_seconds: float
    ) -> ModelReply:
        if self.fail is not None:
            raise self.fail
        self.systems.append(system)
        sent = json.loads(user.split("\n\nYour previous answer")[0])
        legal = sent["legal_actions"][0]
        return ModelReply(
            data={
                "action": legal["type"],
                "team": legal["targets"][: legal["team_size"] or 0],
                "approve": True,
                "success": True,
                "target_id": legal["targets"][0] if legal["targets"] else "",
                "speech": f"{self.name} speaking.",
                "suspects": [],
                "note": "",
                "inner": f"{self.name} thinks as {sent['you']['role']}.",
            },
            input_tokens=100,
            output_tokens=10,
        )


def service(**models: NamedModel | None) -> GameService:
    drivers = {
        name: Driver(name, name.title(), model, 5.0, None if model else "missing")
        for name, model in models.items()
    }
    return GameService(
        drivers=drivers,
        budget=TokenBudget(10_000_000),
        executor=InlineExecutor(),
        new_seed=lambda: 7,
    )


def start(game: GameService, created: CreatedRoom) -> None:
    session = created.session
    game.submit(session, StartGame(player_id=session.seat.player_id, seed=session.room.seed))


def play_out(game: GameService, created: CreatedRoom) -> None:
    """Play the human seat with the table bot until the game is over."""
    session = created.session
    for _ in range(400):
        view = game.view(session)
        if view.phase is Phase.FINISHED:
            return
        assert view.legal_actions, "the game must be waiting for the human"
        import random

        game.submit(session, bot_action(view, random.Random(view.version)))
    raise AssertionError("the game did not finish")


# --- personas --------------------------------------------------------------------------


def test_every_bot_seat_of_the_largest_table_has_a_persona() -> None:
    assert len(BOT_NAMES) == len(set(BOT_NAMES)) == 10
    assert all(persona_for(name) is not None for name in BOT_NAMES)
    assert persona_for("Adam") is None


def test_no_persona_is_named_after_a_role() -> None:
    roles = {role.value for role in Role} | {"merlin", "percival", "morgana", "mordred", "oberon"}

    assert not {persona.name.lower() for persona in PERSONAS} & roles


# --- a model per seat ------------------------------------------------------------------


def test_each_seat_is_played_by_the_model_chosen_for_it() -> None:
    claude, deepseek = NamedModel("claude"), NamedModel("deepseek")
    game = service(claude=claude, deepseek=deepseek)
    created = game.create_room("Adam", 5, seats=["claude", "deepseek", "bot", "bot"])
    room = created.session.room

    assert [(seat.name, seat.agent, seat.driver) for seat in room.seats[1:]] == [
        ("Gawain", "llm", "claude"),
        ("Lancelot", "llm", "deepseek"),
        ("Tristan", "random", None),
        ("Galahad", "random", None),
    ]

    start(game, created)
    play_out(game, created)

    snapshot = game.snapshot(created.session)
    said = {
        entry.data["player"]: entry.data["text"] for entry in snapshot.log if entry.kind == "speech"
    }
    assert said["p2"] == "claude speaking."
    assert said["p3"] == "deepseek speaking."
    assert claude.systems and deepseek.systems


def test_a_model_seat_is_told_its_persona_and_nothing_else_about_it() -> None:
    claude = NamedModel("claude")
    game = service(claude=claude)
    created = game.create_room("Adam", 5, seats=["claude", "bot", "bot", "bot"])
    start(game, created)
    play_out(game, created)

    gawain = persona_for("Gawain")
    assert gawain is not None
    assert all(gawain.manner_en in system for system in claude.systems)
    assert all("never changes what you know" in system for system in claude.systems)


def test_a_seat_whose_model_fails_is_played_by_the_bot_and_says_so() -> None:
    game = service(deepseek=NamedModel("deepseek", fail=ModelUnavailable("API error 402")))
    created = game.create_room("Adam", 5, seats=["deepseek", "bot", "bot", "bot"])
    start(game, created)
    play_out(game, created)

    state = game.snapshot(created.session).agents["p2"]
    assert (state.last_source, state.last_fallback_reason) == ("fallback", "unavailable")


def test_a_seat_whose_driver_is_gone_is_played_by_the_bot() -> None:
    game = service(deepseek=None)
    created = game.create_room("Adam", 5, seats=["deepseek", "bot", "bot", "bot"])
    start(game, created)
    play_out(game, created)

    assert game.snapshot(created.session).agents["p2"].last_fallback_reason == "unavailable"


def test_the_number_of_choices_must_match_the_bot_seats() -> None:
    game = service()

    with pytest.raises(ValueError, match="4 bot seats"):
        game.create_room("Adam", 5, seats=["bot", "bot"])
    with pytest.raises(ValueError, match="5 bot seats"):
        game.create_room("Adam", 5, seats=["bot"] * 4, spectate=True)


# --- thoughts ----------------------------------------------------------------------------


def test_thoughts_stay_hidden_from_a_player_until_the_game_is_over() -> None:
    game = service(claude=NamedModel("claude"))
    created = game.create_room("Adam", 5, seats=["claude", "bot", "bot", "bot"])
    start(game, created)
    session = created.session

    during = game.snapshot(session)
    assert during.view.phase is not Phase.FINISHED
    assert during.thoughts == ()

    play_out(game, created)

    after = game.snapshot(session)
    assert after.thoughts, "the review shows what each AI seat thought"
    versions = [thought.version for thought in after.thoughts]
    assert versions == sorted(versions)
    assert {thought.player_id for thought in after.thoughts} <= {"p2", "p3", "p4", "p5"}
    assert any(thought.text.startswith("claude thinks as") for thought in after.thoughts)


def test_a_bots_thought_is_filed_under_the_speech_it_belongs_to() -> None:
    game = service()
    created = game.create_room("Adam", 5, spectate=True)
    start(game, created)

    snapshot = game.snapshot(created.session)
    speeches = {
        (entry.version, entry.data["player"]) for entry in snapshot.log if entry.kind == "speech"
    }
    thoughts = {(thought.version, thought.player_id) for thought in snapshot.thoughts}
    assert speeches and speeches <= thoughts


def test_a_thought_says_what_the_speech_may_not() -> None:
    game = service()
    created = game.create_room("Adam", 7, spectate=True)
    start(game, created)

    snapshot = game.snapshot(created.session)
    said = " ".join(str(entry.data["text"]) for entry in snapshot.log if entry.kind == "speech")
    thought = " ".join(thought.text for thought in snapshot.thoughts)
    assert any(word in thought for word in ROLE_WORDS)
    assert "我是邪恶方" not in said and "是邪恶方，但不能" not in said


# --- watching from outside ---------------------------------------------------------------


def test_a_spectated_table_is_all_bots_and_plays_itself_to_the_end() -> None:
    game = service()
    created = game.create_room("Adam", 6, spectate=True)
    room, session = created.session.room, created.session

    assert session.is_spectator
    assert [seat.player_id for seat in room.seats] == ["p1", "p2", "p3", "p4", "p5", "p6"]
    assert all(seat.is_bot for seat in room.seats)
    assert room.spectator is not None and room.spectator.name == "Adam"
    assert created.view.you_id == ""
    assert [legal.type for legal in created.view.legal_actions] == ["start_game"]

    start(game, created)

    view = game.view(session)
    assert view.phase is Phase.FINISHED
    assert view.winner is not None
    assert view.legal_actions == ()


def test_a_spectator_sees_every_role_but_a_player_does_not() -> None:
    game = service(claude=NamedModel("claude"))
    watched = game.create_room("Adam", 5, seats=["claude"] + ["bot"] * 4, spectate=True)
    played = game.create_room("Adam", 5, seats=["claude"] + ["bot"] * 3)
    start(game, played)

    # Deal the watched table without letting it finish: hold the model seat back.
    game._executor = type("Held", (), {"submit": lambda self, task: None})()  # type: ignore[assignment]
    start(game, watched)

    spectator = game.snapshot(watched.session)
    player = game.snapshot(played.session)
    assert spectator.spectator and not player.spectator
    assert spectator.view.phase is not Phase.FINISHED
    assert all(info.role is not None for info in spectator.view.players)
    assert all(info.seen_as is None for info in spectator.view.players)
    if player.view.phase is not Phase.FINISHED:
        assert [info.id for info in player.view.players if info.role is not None] == ["p1"]


def test_a_spectator_can_do_nothing_but_start_the_game() -> None:
    game = service(claude=NamedModel("claude"))
    created = game.create_room("Adam", 5, seats=["claude"] + ["bot"] * 4, spectate=True)
    game._executor = type("Held", (), {"submit": lambda self, task: None})()  # type: ignore[assignment]
    start(game, created)
    session = created.session

    for action in (
        VoteTeam(player_id=SPECTATOR_ID, approve=True),
        Speak(player_id="p1", text="let me in"),
        VoteTeam(player_id="p2", approve=True),
    ):
        with pytest.raises(RuleViolation):
            game.submit(session, action)


def test_the_spectators_token_opens_only_their_own_view() -> None:
    game = service()
    created = game.create_room("Adam", 5, spectate=True)

    session = game.authenticate(created.token)

    assert session is not None and session.is_spectator
    assert session.room.game_id == created.session.room.game_id


# --- the same over HTTP ------------------------------------------------------------------


@contextmanager
def api(game: GameService) -> Iterator[TestClient]:
    app.dependency_overrides[get_service] = lambda: game
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_the_lobby_is_told_what_each_driver_is_missing() -> None:
    with api(service(claude=NamedModel("claude"), deepseek=None)) as client:
        config = client.get("/config").json()

    assert config["llm_available"] is True
    assert [persona["name"] for persona in config["personas"]] == list(BOT_NAMES)
    assert config["gm_ai_available"] is False
    assert config["drivers"] == [
        {"id": "claude", "label": "Claude", "available": True, "problem": None},
        {"id": "deepseek", "label": "Deepseek", "available": False, "problem": "missing"},
    ]


def test_choosing_seats_over_http() -> None:
    with api(service(claude=NamedModel("claude"), deepseek=None)) as client:
        body = {"nickname": "Adam", "player_count": 5}

        created = client.post("/rooms", json=body | {"seats": ["claude", "bot", "bot", "bot"]})
        unavailable = client.post(
            "/rooms", json=body | {"seats": ["deepseek", "bot", "bot", "bot"]}
        )
        wrong_count = client.post("/rooms", json=body | {"seats": ["bot"]})
        unknown = client.post("/rooms", json=body | {"seats": ["gpt", "bot", "bot", "bot"]})

    assert created.status_code == 201
    players = created.json()["game"]["players"]
    assert [(p["agent"], p["driver"]) for p in players] == [
        (None, None),
        ("llm", "claude"),
        ("random", None),
        ("random", None),
        ("random", None),
    ]
    assert players[0]["persona"] is None
    assert players[1]["persona"]["title"] == "直率的急先锋"
    assert (unavailable.status_code, unavailable.json()["code"]) == (409, "driver_unavailable")
    assert (wrong_count.status_code, wrong_count.json()["code"]) == (422, "wrong_seat_count")
    assert unknown.status_code == 422


def test_spectating_over_http() -> None:
    with api(service()) as client:
        created = client.post(
            "/rooms", json={"nickname": "Adam", "player_count": 5, "spectate": True}
        ).json()
        headers = {"Authorization": f"Bearer {created['token']}"}
        lobby = created["game"]
        url = f"/games/{created['game_id']}"

        assert lobby["spectator"] is True
        assert lobby["you_id"] == ""
        assert all(not player["is_you"] for player in lobby["players"])
        assert [legal["type"] for legal in lobby["legal_actions"]] == ["start_game"]

        refused = client.post(
            f"{url}/actions", json={"type": "vote_team", "approve": True}, headers=headers
        )
        game = client.post(f"{url}/actions", json={"type": "start_game"}, headers=headers).json()

    assert refused.status_code == 422
    assert game["phase"] == "finished"
    assert all(player["role"] is not None for player in game["players"])
    assert game["thoughts"] and {"version", "player_id", "text"} == set(game["thoughts"][0])
    assert game["log"][-1]["kind"] == "game_finished"


def test_a_players_response_carries_no_thoughts_while_the_game_is_on() -> None:
    with api(service()) as client:
        created = client.post("/rooms", json={"nickname": "Adam", "player_count": 5}).json()
        headers = {"Authorization": f"Bearer {created['token']}"}
        game = client.post(
            f"/games/{created['game_id']}/actions", json={"type": "start_game"}, headers=headers
        ).json()

    assert game["spectator"] is False
    assert game["phase"] != "finished"
    assert game["thoughts"] == []
    assert not any(
        word in json.dumps(game, ensure_ascii=False) for word in ("我是邪恶方", "是邪恶方，但")
    )


# --- stored in a database ---------------------------------------------------------------


@pytest.mark.parametrize("backend", SQL_BACKENDS)
def test_seats_spectator_and_thoughts_survive_a_restart(backend: str, tmp_path: Any) -> None:
    url = database_url(backend, tmp_path)

    def open_service() -> GameService:
        database = Database.from_url(url)
        return GameService(
            SqlGameRepository(database),
            SqlRoomStore(database),
            transaction=database.transaction,
            thoughts=SqlThoughtStore(database),
            drivers={"deepseek": Driver("deepseek", "DeepSeek", NamedModel("deepseek"), 5.0)},
            budget=TokenBudget(10_000_000),
            executor=InlineExecutor(),
        )

    first = open_service()
    created = first.create_room("Adam", 5, seats=["deepseek"] + ["bot"] * 4, spectate=True)
    start(first, created)
    before = first.snapshot(created.session)

    second = open_service()
    session = second.authenticate(created.token)

    assert session is not None and session.is_spectator
    assert session.room.spectator is not None and session.room.spectator.name == "Adam"
    assert [seat.driver for seat in session.room.seats] == ["deepseek", None, None, None, None]
    after = second.snapshot(session)
    assert after.view.phase is Phase.FINISHED
    assert after.thoughts == before.thoughts != ()
