"""Model-driven seats and the AI game master inside a running game."""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.model import ModelReply, ModelTimeout
from app.agents.policy_fallback import choose_action
from app.agents.state import AgentState, AgentStateStore, InMemoryAgentStateStore
from app.api.deps import build_service, get_service
from app.config import Settings
from app.game.actions import StartGame
from app.game.state import Phase
from app.game.views import PlayerView
from app.main import app
from app.service import CreatedRoom, GameService, InlineExecutor, Session
from app.storage.agent_states import SqlAgentStateStore
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from tests.game.scenarios import lobby
from tests.storage.conftest import SQL_BACKENDS, database_url


class LegalModel:
    """Stands in for a language model: always answers with a legal move.

    It only uses what it is sent, like a real model would, so a game played
    with it exercises the whole path from observation to stored event.
    """

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.player_questions: list[dict[str, Any]] = []
        self.gm_questions: list[dict[str, Any]] = []

    def complete(
        self, *, system: str, user: str, schema: Mapping[str, Any], timeout_seconds: float
    ) -> ModelReply:
        if self.fail is not None:
            raise self.fail
        sent = json.loads(user.split("\n\nYour previous answer")[0])

        if "tone" in schema["properties"]:
            self.gm_questions.append(sent)
            answer: dict[str, Any] = {
                "tone": "tense",
                "announcement": f"The hall holds its breath ({sent['event']['version']}).",
                "rule_hint": "none",
            }
        else:
            self.player_questions.append(sent)
            legal = sent["legal_actions"][0]
            answer = {
                "action": legal["type"],
                "team": legal["targets"][: legal["team_size"] or 0],
                "approve": True,
                "success": True,
                "target_id": legal["targets"][0] if legal["targets"] else "",
                "speech": "I have nothing to add.",
                "suspects": [],
                "note": f"{sent['you']['id']} saw version {len(sent['public_history'])}",
            }
        return ModelReply(data=answer, input_tokens=1000, output_tokens=50)


class DeferredExecutor:
    """Holds background work until the test says go, to observe the waiting state."""

    def __init__(self) -> None:
        self.tasks: list[Callable[[], None]] = []

    def submit(self, task: Callable[[], None]) -> object:
        self.tasks.append(task)
        return None

    def run_all(self) -> None:
        while self.tasks:
            self.tasks.pop(0)()


SETTINGS = Settings(llm_input_price_per_mtok=4.0, llm_output_price_per_mtok=20.0)


def service_with(model: LegalModel | None, executor: Any = None, url: str | None = None) -> Any:
    return build_service(url, SETTINGS, model=model, executor=executor or InlineExecutor())


def start(service: GameService, created: CreatedRoom) -> PlayerView:
    session = created.session
    return service.submit(session, StartGame(player_id="p1", seed=session.room.seed))


def start_waiting_on_ai(service: GameService, executor: DeferredExecutor) -> CreatedRoom:
    """A started game whose first move belongs to a model seat.

    Who leads first depends on the server's random seed, so rooms are opened
    until one starts with an AI seat as leader (4 in 5 do).
    """
    for _ in range(50):
        executor.tasks.clear()
        created = service.create_room("Adam", 5, ai_seats=4)
        start(service, created)
        if service.snapshot(created.session).thinking:
            return created
    raise AssertionError("no game started with an AI seat to move")


def play_out(service: GameService, session: Session, view: PlayerView, seed: int = 1) -> PlayerView:
    """Play the human seat with random legal moves until the game is over."""
    rng = random.Random(seed)
    for _ in range(300):
        view = service.view(session)
        if view.phase is Phase.FINISHED:
            return view
        assert view.legal_actions, "with an inline executor the game always waits for the human"
        view = service.submit(session, choose_action(view, rng))
    raise AssertionError("the game did not finish")


# --- Whole games -------------------------------------------------------------


@pytest.mark.parametrize("player_count", [5, 7, 10])
def test_game_with_only_model_seats_plays_to_the_end(player_count: int) -> None:
    model = LegalModel()
    service = service_with(model)
    created = service.create_room("Adam", player_count, ai_seats=player_count - 1)

    final = play_out(service, created.session, start(service, created))

    assert final.winner is not None
    snapshot = service.snapshot(created.session)
    assert snapshot.thinking == ()
    acted = {seat for seat, state in snapshot.agents.items() if state.last_source == "model"}
    assert acted == {f"p{number}" for number in range(2, player_count + 1)}
    assert all(state.last_fallback_reason is None for state in snapshot.agents.values())
    assert snapshot.usage.calls == len(model.player_questions) > 0
    assert snapshot.cost_usd == pytest.approx(snapshot.usage.calls * (1000 * 4 + 50 * 20) / 1e6)


def test_model_seats_and_random_bots_share_a_table() -> None:
    model = LegalModel()
    service = service_with(model)
    created = service.create_room("Adam", 7, ai_seats=2)
    room = created.session.room

    assert [(seat.agent, seat.style) for seat in room.seats] == [
        (None, None),
        ("llm", "baseline"),
        ("llm", "baseline"),
        ("random", None),
        ("random", None),
        ("random", None),
        ("random", None),
    ]
    final = play_out(service, created.session, start(service, created))

    assert final.winner is not None
    assert {question["you"]["id"] for question in model.player_questions} == {"p2", "p3"}
    assert set(service.snapshot(created.session).agents) == {"p2", "p3"}


def test_slow_model_never_blocks_the_game() -> None:
    service = service_with(LegalModel(fail=ModelTimeout("slow")))
    created = service.create_room("Adam", 5, ai_seats=4)

    final = play_out(service, created.session, start(service, created))

    assert final.winner is not None
    states = service.snapshot(created.session).agents
    assert {state.last_source for state in states.values()} == {"fallback"}
    assert {state.last_fallback_reason for state in states.values()} == {"timeout"}


def test_room_with_model_seats_still_plays_on_a_server_without_a_model() -> None:
    """For example after a restart with LLM_PROVIDER switched off."""
    service = GameService(executor=InlineExecutor())
    created = service.create_room("Adam", 5, ai_seats=2)

    final = play_out(service, created.session, start(service, created))

    assert final.winner is not None
    states = service.snapshot(created.session).agents
    assert {state.last_fallback_reason for state in states.values()} == {"unavailable"}
    assert not service.llm_available


def test_ai_seats_must_fit_the_table() -> None:
    service = service_with(LegalModel())

    for ai_seats in (-1, 5):
        with pytest.raises(ValueError, match="ai_seats"):
            service.create_room("Adam", 5, ai_seats=ai_seats)


# --- Background turns --------------------------------------------------------


def test_request_returns_before_the_model_has_played() -> None:
    model, executor = LegalModel(), DeferredExecutor()
    service = service_with(model, executor)

    created = start_waiting_on_ai(service, executor)

    # The human's request is done, and no model has been asked anything yet.
    assert model.player_questions == []
    waiting = service.snapshot(created.session)
    assert waiting.thinking
    assert set(waiting.thinking) <= {"p2", "p3", "p4", "p5"}

    executor.run_all()

    after = service.snapshot(created.session)
    assert model.player_questions
    assert after.view.version > waiting.view.version
    assert after.thinking == () or after.view.legal_actions


def test_only_one_background_run_per_game() -> None:
    executor = DeferredExecutor()
    service = service_with(LegalModel(), executor)
    created = start_waiting_on_ai(service, executor)

    for _ in range(5):
        service.view(created.session)

    assert len(executor.tasks) == 1


def position_where_everyone_votes(
    service: GameService, executor: DeferredExecutor
) -> tuple[CreatedRoom, PlayerView]:
    """A team vote in which the human and the model seats all still have to vote."""
    for _ in range(40):
        created = service.create_room("Adam", 5, ai_seats=4)
        start(service, created)
        for _ in range(30):
            view = service.view(created.session)
            waiting = set(service.snapshot(created.session).thinking)
            if (
                view.phase is Phase.TEAM_VOTE
                and view.legal_actions
                and waiting == {"p2", "p3", "p4", "p5"}
            ):
                return created, view
            if view.legal_actions and view.phase is not Phase.TEAM_VOTE:
                service.submit(created.session, choose_action(view, random.Random(1)))
            # One background step at a time, so the vote is caught before the models cast theirs.
            if executor.tasks:
                service._play_one_ai_turn(created.session.room)
            if view.phase is Phase.FINISHED:
                break
    raise AssertionError("no game reached a vote with everyone still to vote")


def test_human_can_vote_while_the_models_are_still_thinking() -> None:
    model = LegalModel()
    service = service_with(model, DeferredExecutor())
    created, view = position_where_everyone_votes(service, service._executor)
    room = created.session.room

    # A model starts thinking about its vote...
    original_decide = service._decide
    human_voted: list[int] = []

    def decide_while_the_human_votes(*args: Any) -> Any:
        decided = original_decide(*args)
        if not human_voted:
            # ...and before its answer is stored, the human's vote arrives.
            voted = service.submit(created.session, choose_action(view, random.Random(1)))
            human_voted.append(voted.version)
        return decided

    service._decide = decide_while_the_human_votes
    asked_before = len(model.player_questions)

    assert service._play_one_ai_turn(room)

    # The model's vote was kept: same choice in front of it, so it was not asked again.
    assert len(model.player_questions) == asked_before + 1
    after = service.view(created.session)
    assert after.version == human_voted[0] + 1
    assert set(after.team_voted) >= {"p1"}
    assert len(after.team_voted) == 2 or after.phase is not Phase.TEAM_VOTE


def test_pending_model_turn_resumes_after_a_restart(tmp_path: Path) -> None:
    url = database_url("sqlite", tmp_path)
    lost_work = DeferredExecutor()
    before = service_with(LegalModel(), lost_work, url)
    created = start_waiting_on_ai(before, lost_work)
    stuck = before.snapshot(created.session)
    assert stuck.thinking
    # The process dies here: the queued background work is lost.

    model = LegalModel()
    after = service_with(model, InlineExecutor(), url)
    session = after.authenticate(created.token)
    assert session is not None

    view = after.view(session)  # any poll from the client

    resumed = after.snapshot(session)
    assert model.player_questions
    assert resumed.view.version > stuck.view.version
    assert resumed.thinking == () or view.legal_actions or resumed.view.legal_actions


# --- Memory ------------------------------------------------------------------


def test_each_seat_gets_back_its_own_note_and_nobody_elses() -> None:
    model = LegalModel()
    service = service_with(model)
    created = service.create_room("Adam", 5, ai_seats=4)

    play_out(service, created.session, start(service, created))

    last_note: dict[str, str] = {}
    for question in model.player_questions:
        seat = question["you"]["id"]
        assert question["your_notes"] == last_note.get(seat, "")
        last_note[seat] = f"{seat} saw version {len(question['public_history'])}"
    assert len(last_note) == 4
    stored = service.snapshot(created.session).agents
    assert {seat: state.note for seat, state in stored.items()} == last_note


def test_fallback_turn_keeps_the_previous_note() -> None:
    model = LegalModel()
    service = service_with(model)
    created = service.create_room("Adam", 5, ai_seats=4)
    start(service, created)
    # Play until every model seat has had a turn of its own and left itself a note.
    notes: dict[str, str] = {}
    while len(notes) < 4:
        view = service.view(created.session)
        service.submit(created.session, choose_action(view, random.Random(1)))
        notes = {seat: s.note for seat, s in service.snapshot(created.session).agents.items()}
    assert len(notes) == 4

    model.fail = ModelTimeout("slow")
    play_out(service, created.session, service.view(created.session))

    for seat, state in service.snapshot(created.session).agents.items():
        if seat in notes:
            assert state.note == notes[seat]


@pytest.fixture(params=["memory", *SQL_BACKENDS])
def agent_states(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[AgentStateStore]:
    if request.param == "memory":
        yield InMemoryAgentStateStore()
        return
    database = Database.from_url(database_url(request.param, tmp_path))
    SqlGameRepository(database).create(lobby())
    yield SqlAgentStateStore(database)
    database.dispose()


def test_agent_state_store_contract(agent_states: AgentStateStore) -> None:
    game_id = lobby().game_id
    assert agent_states.get(game_id, "p2") == AgentState()
    assert agent_states.for_game(game_id) == {}

    first = AgentState(note="p4 rejected twice", last_source="model")
    agent_states.put(game_id, "p2", first)
    agent_states.put(
        game_id, "p3", AgentState(last_source="fallback", last_fallback_reason="timeout")
    )
    assert agent_states.get(game_id, "p2") == first

    second = AgentState(note="p4 is evil", last_source="model")
    agent_states.put(game_id, "p2", second)

    assert agent_states.for_game(game_id) == {
        "p2": second,
        "p3": AgentState(last_source="fallback", last_fallback_reason="timeout"),
    }
    assert agent_states.for_game("another-game") == {}


# --- Game master -------------------------------------------------------------


def test_template_game_master_announces_public_events_in_the_rooms_language() -> None:
    service = service_with(None)
    created = service.create_room("Adam", 5, gm="template", language="en")
    start(service, created)

    announcements = service.snapshot(created.session).announcements

    assert announcements
    assert announcements[0].facts.startswith("Mission 1 begins.")
    assert {item.source for item in announcements} == {"template"}
    assert [item.version for item in announcements] == sorted(
        item.version for item in announcements
    )


def test_game_master_can_be_switched_off() -> None:
    service = service_with(LegalModel())
    created = service.create_room("Adam", 5, gm="off")
    start(service, created)

    assert service.snapshot(created.session).announcements == ()


def test_ai_game_master_colours_events_in_the_background_and_only_once() -> None:
    model, executor = LegalModel(), DeferredExecutor()
    service = service_with(model, executor)
    created = service.create_room("Adam", 5, gm="ai", language="en")
    start(service, created)

    # Not narrated yet: the client is shown the template meanwhile.
    pending = service.snapshot(created.session).announcements
    assert {item.source for item in pending} == {"template"}
    assert model.gm_questions == []

    executor.run_all()
    narrated = service.snapshot(created.session).announcements
    asked = len(model.gm_questions)

    assert {item.source for item in narrated} == {"model"}
    assert [item.facts for item in narrated] == [item.facts for item in pending]
    assert all("holds its breath" in item.announcement for item in narrated)
    for _ in range(3):
        service.snapshot(created.session)
    assert len(model.gm_questions) == asked == len(narrated)


def test_game_master_is_never_sent_a_role() -> None:
    model = LegalModel()
    service = service_with(model)
    created = service.create_room("Adam", 7, ai_seats=6, gm="ai")

    play_out(service, created.session, start(service, created))

    assert model.gm_questions
    roles = {"merlin", "assassin", "loyal_servant", "minion"}
    for question in model.gm_questions:
        assert not roles & {str(value) for value in question["event"].values()}


def test_only_the_latest_announcements_are_kept_in_a_response() -> None:
    service = service_with(None)
    created = service.create_room("Adam", 10)

    play_out(service, created.session, start(service, created))

    announcements = service.snapshot(created.session).announcements
    assert len(announcements) == 12
    assert "game is over" in announcements[-1].facts or "对局结束" in announcements[-1].facts


# --- HTTP --------------------------------------------------------------------


@contextmanager
def api(service: GameService) -> Iterator[TestClient]:
    app.dependency_overrides[get_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def create(client: TestClient, **body: Any) -> Any:
    return client.post("/rooms", json={"nickname": "Adam", "player_count": 5, **body})


def test_server_without_a_model_says_so_and_refuses_ai_rooms() -> None:
    with api(service_with(None)) as client:
        assert client.get("/config").json() == {"llm_available": False}

        for body in ({"ai_seats": 1}, {"gm": "ai"}):
            response = create(client, **body)
            assert response.status_code == 409
            assert response.json()["code"] == "llm_not_configured"

        assert create(client, gm="template").status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"ai_seats": 5},
        {"ai_seats": -1},
        {"ai_seats": "many"},
        {"ai_style": "reckless"},
        {"gm": "human"},
        {"language": "fr"},
    ],
)
def test_invalid_room_options_are_422(body: dict[str, Any]) -> None:
    with api(service_with(LegalModel())) as client:
        assert create(client, **body).status_code == 422


def test_room_with_ai_seats_over_http() -> None:
    with api(service_with(LegalModel())) as client:
        assert client.get("/config").json() == {"llm_available": True}

        response = create(client, ai_seats=2, ai_style="cautious", gm="ai", language="en")
        assert response.status_code == 201
        room = response.json()
        headers = {"Authorization": f"Bearer {room['token']}"}
        assert [player["agent"] for player in room["game"]["players"]] == [
            None,
            "llm",
            "llm",
            "random",
            "random",
        ]
        assert room["game"]["gm"] == "ai"
        assert room["game"]["announcements"] == []

        started = client.post(
            f"/games/{room['game_id']}/actions", json={"type": "start_game"}, headers=headers
        ).json()
        polled = client.get(f"/games/{room['game_id']}", headers=headers).json()

    assert started["announcements"][0]["facts"].startswith("Mission 1 begins.")
    assert polled["announcements"][0]["source"] == "model"
    assert set(polled["announcements"][0]) == {
        "version",
        "tone",
        "facts",
        "announcement",
        "rule_hint",
        "source",
    }
    assert polled["ai_usage"]["calls"] > 0
    assert polled["ai_usage"]["cost_usd"] > 0
    for player in polled["players"]:
        assert set(player) >= {"agent", "thinking", "last_turn", "fallback_reason"}


def test_private_notes_never_reach_a_client() -> None:
    service = service_with(LegalModel())
    with api(service) as client:
        # Open rooms until one starts with an AI seat as leader, so a note exists.
        for _ in range(50):
            room = create(client, ai_seats=4).json()
            headers = {"Authorization": f"Bearer {room['token']}"}
            client.post(
                f"/games/{room['game_id']}/actions", json={"type": "start_game"}, headers=headers
            )
            body = client.get(f"/games/{room['game_id']}", headers=headers).text
            session = service.authenticate(room["token"])
            assert session is not None
            states = service.snapshot(session).agents.values()
            notes = [state.note for state in states if state.note]
            if notes:
                break

    assert notes
    assert "note" not in body
    assert all(note not in body for note in notes)


def test_waiting_seats_are_flagged_for_the_client() -> None:
    executor = DeferredExecutor()
    with api(service_with(LegalModel(), executor)) as client:
        # Open rooms until one starts with an AI seat as the first leader.
        for _ in range(50):
            executor.tasks.clear()
            room = create(client, ai_seats=4).json()
            headers = {"Authorization": f"Bearer {room['token']}"}
            started = client.post(
                f"/games/{room['game_id']}/actions", json={"type": "start_game"}, headers=headers
            ).json()
            thinking = [player["id"] for player in started["players"] if player["thinking"]]
            if thinking:
                break
        assert thinking
        assert "p1" not in thinking

        executor.run_all()
        later = client.get(f"/games/{room['game_id']}", headers=headers).json()

    assert later["version"] > started["version"]
    assert any(player["last_turn"] == "model" for player in later["players"])
