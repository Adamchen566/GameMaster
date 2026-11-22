"""Every game is kept in full, and can be exported to replay it later."""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from app.agents.drivers import Driver
from app.agents.model import ModelReply, ModelTimeout, TokenBudget
from app.agents.table_bot import choose_action as bot_action
from app.api import deps
from app.config import Settings
from app.game.actions import StartGame
from app.game.codec import decode_event
from app.game.engine import evolve, new_game
from app.game.rulesets import OFFICIAL
from app.game.state import Phase
from app.records import FORMAT, game_record, main
from app.service import CreatedRoom, GameService, InlineExecutor
from app.storage.agent_states import SqlAgentStateStore
from app.storage.database import Database
from app.storage.games import SqlGameRepository
from app.storage.rooms import SqlRoomStore
from app.storage.thoughts import SqlThoughtStore
from app.storage.turns import SqlTurnStore


class PickyModel:
    """Answers with an illegal team first, then a legal move: both answers must be kept."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.calls = 0

    def complete(
        self, *, system: str, user: str, schema: Mapping[str, Any], timeout_seconds: float
    ) -> ModelReply:
        if self.fail is not None:
            raise self.fail
        self.calls += 1
        sent = json.loads(user.split("\n\nYour previous answer")[0])
        legal = sent["legal_actions"][0]
        retry = "Your previous answer" in user
        team = legal["targets"][: legal["team_size"] or 0]
        if legal["type"] == "propose_team" and not retry:
            team = ["nobody"] * len(team)
        return ModelReply(
            data={
                "action": legal["type"],
                "team": team,
                "approve": True,
                "success": True,
                "target_id": legal["targets"][0] if legal["targets"] else "",
                "speech": "Fine by me.",
                "suspects": [],
                "note": "",
                "inner": "thinking",
            },
            input_tokens=300,
            output_tokens=20,
        )


def sql_service(url: str, model: Any) -> GameService:
    deps.migrate(url)
    database = Database.from_url(url)
    return GameService(
        SqlGameRepository(database),
        SqlRoomStore(database),
        transaction=database.transaction,
        agent_states=SqlAgentStateStore(database),
        thoughts=SqlThoughtStore(database),
        turns=SqlTurnStore(database),
        drivers={"codex": Driver("codex", "Codex", model, 5.0)},
        budget=TokenBudget(10_000_000),
        executor=InlineExecutor(),
    )


def play_spectated(service: GameService) -> CreatedRoom:
    created = service.create_room(
        "Adam", 5, seats=["codex", "bot", "bot", "bot", "bot"], spectate=True
    )
    session = created.session
    service.submit(session, StartGame(player_id=session.seat.player_id, seed=session.room.seed))
    assert service.view(session).phase is Phase.FINISHED
    return created


def test_every_model_turn_is_kept_with_what_it_saw_and_every_answer(tmp_path: Path) -> None:
    model = PickyModel()
    service = sql_service(f"sqlite:///{tmp_path / 'games.db'}", model)
    created = play_spectated(service)

    turns = service.turns(created.session.room.game_id)

    assert turns, "the model seat played"
    assert {turn.player_id for turn in turns} == {"p1"}
    assert all(turn.driver == "codex" and turn.source == "model" for turn in turns)
    assert sum(turn.attempts for turn in turns) == model.calls
    assert all(
        turn.observation is not None and turn.observation["you"]["id"] == "p1" for turn in turns
    )
    assert all(turn.input_tokens == 300 * turn.attempts for turn in turns)
    # The answer the game turned down is kept, with the reason, next to the one it took.
    proposals = [
        turn for turn in turns if turn.observation and turn.observation["phase"] == "team_proposal"
    ]
    if proposals:
        first = proposals[0]
        assert first.attempts == 2
        assert "rejected" in first.exchanges[0] and "rejected" not in first.exchanges[1]
    versions = [turn.version for turn in turns]
    assert versions == sorted(versions)


def test_a_failed_model_turn_is_kept_with_its_error(tmp_path: Path) -> None:
    service = sql_service(
        f"sqlite:///{tmp_path / 'games.db'}", PickyModel(fail=ModelTimeout("slow"))
    )
    created = play_spectated(service)

    turns = service.turns(created.session.room.game_id)

    assert turns and all(turn.source == "fallback" for turn in turns)
    assert all(turn.fallback_reason == "timeout" for turn in turns)
    assert all(turn.exchanges == ({"error": "timeout"},) for turn in turns)


def test_the_export_holds_everything_and_rebuilds_the_game(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'games.db'}"
    service = sql_service(url, PickyModel())
    created = play_spectated(service)
    game_id = created.session.room.game_id

    record = game_record(Database.from_url(url), game_id)

    assert record["format"] == FORMAT
    assert record["room"]["spectated"] is True
    assert [seat["driver"] for seat in record["seats"]] == ["codex", None, None, None, None]
    assert all(seat["role"] is not None for seat in record["seats"])
    assert record["seats"][0]["persona"] == "直率的急先锋"
    assert record["result"]["phase"] == "finished"
    assert record["thoughts"] and record["model_turns"]
    assert record["public_log"][-1]["kind"] == "game_finished"
    # The secrets are there too: every ballot and mission card.
    assert {"team_vote_cast", "mission_vote_cast", "game_started"} <= {
        event["type"] for event in record["events"]
    }
    # Replaying the events rebuilds the very same final position.
    state = new_game(
        game_id=game_id,
        ruleset=OFFICIAL,
        player_ids=[seat["player_id"] for seat in record["seats"]],
        host_id=record["seats"][0]["player_id"],
    )
    for event in record["events"]:
        state = evolve(state, decode_event(event["type"], event["payload"]))
    assert state.phase is Phase.FINISHED
    assert state.version == record["result"]["version"]
    assert state.winner is not None and state.winner.value == record["result"]["winner"]
    json.dumps(record, ensure_ascii=False)


def test_the_command_lists_games_and_writes_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'games.db'}"
    service = sql_service(url, PickyModel())
    game_id = play_spectated(service).session.room.game_id
    monkeypatch.setattr(
        "app.records.get_settings", lambda: Settings(_env_file=None, database_url=url)
    )  # type: ignore[call-arg]

    assert main([]) == 0
    assert game_id in capsys.readouterr().out

    out = tmp_path / "game.json"
    assert main([game_id, "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["game_id"] == game_id


def test_the_default_database_is_a_file_created_and_migrated_on_first_use(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'nested' / 'data' / 'avalon.db'}"

    service = deps.build_service(url, Settings(_env_file=None))  # type: ignore[call-arg]
    deps.migrate(url)
    service = deps.build_service(url, Settings(_env_file=None))  # type: ignore[call-arg]
    created = service.create_room("Adam", 5)

    assert (tmp_path / "nested" / "data" / "avalon.db").exists()
    reopened = deps.build_service(url, Settings(_env_file=None))  # type: ignore[call-arg]
    assert reopened.authenticate(created.token) is not None
    assert Settings(_env_file=None).database_url.startswith("sqlite:///")  # type: ignore[call-arg]


def test_memory_keeps_nothing_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    service = deps.build_service("memory", Settings(_env_file=None))  # type: ignore[call-arg]
    service.create_room("Adam", 5)

    assert list(tmp_path.iterdir()) == []
    assert deps.database_for(Settings(_env_file=None, database_url="memory")) is None  # type: ignore[call-arg]


def test_a_human_game_keeps_the_same_full_record(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'games.db'}"
    service = sql_service(url, PickyModel())
    created = service.create_room("Adam", 5, seats=["codex", "bot", "bot", "bot"])
    session = created.session
    service.submit(session, StartGame(player_id="p1", seed=session.room.seed))
    for _ in range(400):
        view = service.view(session)
        if view.phase is Phase.FINISHED:
            break
        service.submit(session, bot_action(view, random.Random(view.version)))

    record = game_record(Database.from_url(url), session.room.game_id)

    assert record["room"]["spectated"] is False
    assert record["seats"][0] | {"role": None} == {
        "player_id": "p1",
        "seat": 0,
        "name": "Adam",
        "is_bot": False,
        "agent": None,
        "driver": None,
        "style": None,
        "persona": None,
        "role": None,
    }
    assert {turn["player_id"] for turn in record["model_turns"]} == {"p2"}
