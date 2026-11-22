"""Request and response shapes of the HTTP API.

Responses are built from a `Snapshot` (a `PlayerView` plus public table status),
never from `GameState`, so nothing a player may not know can reach the wire.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StrictBool, StringConstraints

from app.agents.personas import persona_for
from app.agents.state import AgentState
from app.agents.turns import TurnRecord
from app.game.actions import (
    Action,
    Assassinate,
    ProposeTeam,
    Speak,
    StartGame,
    VoteMission,
    VoteTeam,
)
from app.rooms import Room, Seat
from app.service import Snapshot

Nickname = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class CreateRoomRequest(BaseModel):
    nickname: Nickname
    player_count: int
    ai_seats: int = Field(default=0, ge=0)
    """How many of the bot seats are played by a model instead of the random bot."""
    ai_style: Literal["baseline", "cautious", "aggressive"] = "baseline"
    gm: Literal["off", "template", "ai"] = "template"
    language: Literal["zh", "en"] = "zh"
    seats: list[Literal["bot", "claude", "deepseek", "claude_code", "codex"]] | None = None
    """Who plays each bot seat, in seat order. Replaces `ai_seats` when given."""
    spectate: bool = False
    """Nobody sits down: every seat is a bot and you watch, seeing every role."""


class _ActionRequest(BaseModel):
    expected_version: int | None = None


class StartGameRequest(_ActionRequest):
    type: Literal["start_game"]

    def to_action(self, player_id: str, seed: int) -> Action:
        return StartGame(player_id=player_id, seed=seed, expected_version=self.expected_version)


class ProposeTeamRequest(_ActionRequest):
    type: Literal["propose_team"]
    team: list[str] = Field(max_length=20)

    def to_action(self, player_id: str, seed: int) -> Action:
        return ProposeTeam(
            player_id=player_id, team=tuple(self.team), expected_version=self.expected_version
        )


class SpeakRequest(_ActionRequest):
    type: Literal["speak"]
    # Generous here; the rules engine applies the real limit after cleaning.
    text: str = Field(default="", max_length=2000)
    suspects: list[str] = Field(default_factory=list, max_length=20)

    def to_action(self, player_id: str, seed: int) -> Action:
        return Speak(
            player_id=player_id,
            text=self.text,
            suspects=tuple(self.suspects),
            expected_version=self.expected_version,
        )


class VoteTeamRequest(_ActionRequest):
    type: Literal["vote_team"]
    approve: StrictBool

    def to_action(self, player_id: str, seed: int) -> Action:
        return VoteTeam(
            player_id=player_id, approve=self.approve, expected_version=self.expected_version
        )


class VoteMissionRequest(_ActionRequest):
    type: Literal["vote_mission"]
    success: StrictBool

    def to_action(self, player_id: str, seed: int) -> Action:
        return VoteMission(
            player_id=player_id, success=self.success, expected_version=self.expected_version
        )


class AssassinateRequest(_ActionRequest):
    type: Literal["assassinate"]
    target_id: str

    def to_action(self, player_id: str, seed: int) -> Action:
        return Assassinate(
            player_id=player_id, target_id=self.target_id, expected_version=self.expected_version
        )


ActionRequest = Annotated[
    StartGameRequest
    | ProposeTeamRequest
    | SpeakRequest
    | VoteTeamRequest
    | VoteMissionRequest
    | AssassinateRequest,
    Field(discriminator="type"),
]


class PersonaOut(BaseModel):
    title: str
    manner: str
    color: str
    pitch: float
    rate: float


class ThoughtOut(BaseModel):
    version: int
    player_id: str
    text: str


class PlayerOut(BaseModel):
    id: str
    seat: int
    name: str
    is_bot: bool
    agent: str | None
    """ "random" or "llm" for a bot seat. """
    driver: str | None
    """Which model plays an "llm" seat; None is the server's default."""
    persona: PersonaOut | None
    thinking: bool
    """The game is waiting for this AI seat."""
    last_turn: str | None
    """How this AI seat's latest turn was decided: "model" or "fallback"."""
    fallback_reason: str | None
    is_you: bool
    is_host: bool
    is_leader: bool
    role: str | None
    alignment: str | None
    seen_as: str | None


class MissionOut(BaseModel):
    number: int
    team_size: int
    fails_required: int
    team: list[str]
    outcome: str | None
    fail_votes: int | None


class TeamVoteOut(BaseModel):
    mission_number: int
    proposal_number: int
    team: list[str]
    approvals: list[str]
    rejections: list[str]
    approved: bool


class SpeechOut(BaseModel):
    player_id: str
    text: str
    suspects: list[str]


class LegalActionOut(BaseModel):
    type: str
    team_size: int | None
    targets: list[str]
    can_fail: bool


class AnnouncementOut(BaseModel):
    version: int
    tone: str
    facts: str
    announcement: str
    rule_hint: str
    source: str


class AiUsageOut(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class GameOut(BaseModel):
    game_id: str
    room_code: str
    gm: str
    announcements: list[AnnouncementOut]
    log: list[dict[str, object]]
    spectator: bool
    """You watch from outside the table: every role is shown and you have no seat."""
    thoughts: list[ThoughtOut]
    """What the AI seats really thought. Empty for a player until the game is over."""
    """The public record of the game, oldest first: proposals, speeches, vote and mission results."""
    ai_usage: AiUsageOut
    version: int
    phase: str
    you_id: str
    leader_id: str | None
    players: list[PlayerOut]
    missions: list[MissionOut]
    current_mission_number: int | None
    proposal_number: int | None
    max_rejected_proposals: int
    missions_to_win: int
    ruleset_id: str
    """"official" for 5-10 players, "extended" for the 11-12 house rules."""
    evil_count: int
    proposed_team: list[str]
    speeches: list[SpeechOut]
    """What has been said about the latest proposal, in speaking order."""
    speaker_id: str | None
    team_voted: list[str]
    your_team_vote: bool | None
    last_team_vote: TeamVoteOut | None
    mission_played: list[str]
    your_mission_card: bool | None
    assassin_id: str | None
    assassination_target_id: str | None
    winner: str | None
    win_reason: str | None
    legal_actions: list[LegalActionOut]

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot, room: Room) -> GameOut:
        view = snapshot.view
        seats = {seat.player_id: seat for seat in room.seats}
        vote = view.last_team_vote
        return cls(
            game_id=view.game_id,
            room_code=room.code,
            gm=room.gm,
            announcements=[
                AnnouncementOut(
                    version=item.version,
                    tone=item.tone,
                    facts=item.facts,
                    announcement=item.announcement,
                    rule_hint=item.rule_hint,
                    source=item.source,
                )
                for item in snapshot.announcements
            ],
            log=[entry.to_json() for entry in snapshot.log],
            spectator=snapshot.spectator,
            thoughts=[
                ThoughtOut(version=item.version, player_id=item.player_id, text=item.text)
                for item in snapshot.thoughts
            ],
            ai_usage=AiUsageOut(
                calls=snapshot.usage.calls,
                input_tokens=snapshot.usage.input_tokens,
                output_tokens=snapshot.usage.output_tokens,
                cost_usd=snapshot.cost_usd,
            ),
            version=view.version,
            phase=view.phase,
            you_id=view.you_id,
            leader_id=view.leader_id,
            players=[
                PlayerOut(
                    id=player.id,
                    seat=player.seat,
                    name=seats[player.id].name,
                    is_bot=seats[player.id].is_bot,
                    agent=_agent(seats[player.id]),
                    driver=seats[player.id].driver,
                    persona=_persona(seats[player.id]),
                    thinking=player.id in snapshot.thinking,
                    # The agent's private note is deliberately not part of the response.
                    last_turn=_state(snapshot, player.id).last_source,
                    fallback_reason=_state(snapshot, player.id).last_fallback_reason,
                    is_you=player.id == view.you_id,
                    is_host=player.id == view.host_id,
                    is_leader=player.id == view.leader_id,
                    role=player.role,
                    alignment=player.alignment,
                    seen_as=player.seen_as,
                )
                for player in view.players
            ],
            missions=[
                MissionOut(
                    number=mission.number,
                    team_size=mission.team_size,
                    fails_required=mission.fails_required,
                    team=list(mission.team),
                    outcome=mission.outcome,
                    fail_votes=mission.fail_votes,
                )
                for mission in view.missions
            ],
            current_mission_number=view.current_mission_number,
            proposal_number=view.proposal_number,
            max_rejected_proposals=view.max_rejected_proposals,
            missions_to_win=view.missions_to_win,
            ruleset_id=view.ruleset_id,
            evil_count=view.evil_count,
            proposed_team=list(view.proposed_team),
            speeches=[
                SpeechOut(
                    player_id=speech.player_id, text=speech.text, suspects=list(speech.suspects)
                )
                for speech in view.speeches
            ],
            speaker_id=view.speaker_id,
            team_voted=list(view.team_voted),
            your_team_vote=view.your_team_vote,
            last_team_vote=None
            if vote is None
            else TeamVoteOut(
                mission_number=vote.mission_number,
                proposal_number=vote.proposal_number,
                team=list(vote.team),
                approvals=list(vote.approvals),
                rejections=list(vote.rejections),
                approved=vote.approved,
            ),
            mission_played=list(view.mission_played),
            your_mission_card=view.your_mission_card,
            assassin_id=view.assassin_id,
            assassination_target_id=view.assassination_target_id,
            winner=view.winner,
            win_reason=view.win_reason,
            legal_actions=[
                LegalActionOut(
                    type=legal.type,
                    team_size=legal.team_size,
                    targets=list(legal.targets),
                    can_fail=legal.can_fail,
                )
                for legal in view.legal_actions
            ],
        )


def _agent(seat: Seat) -> str | None:
    return (seat.agent or "random") if seat.is_bot else None


def _persona(seat: Seat) -> PersonaOut | None:
    persona = persona_for(seat.name) if seat.is_bot else None
    if persona is None:
        return None
    return PersonaOut(
        title=persona.title,
        manner=persona.manner,
        color=persona.color,
        pitch=persona.pitch,
        rate=persona.rate,
    )


def _state(snapshot: Snapshot, player_id: str) -> AgentState:
    return snapshot.agents.get(player_id, AgentState())


class DriverOut(BaseModel):
    id: str
    label: str
    available: bool
    problem: str | None
    """Why it cannot be used right now: a short code, e.g. "missing_deepseek_api_key"."""


class SeatPersonaOut(BaseModel):
    name: str
    title: str
    manner: str
    color: str


class ConfigOut(BaseModel):
    llm_available: bool
    """Whether this server can run model-driven seats at all."""
    gm_ai_available: bool
    """Whether the game master can be voiced by a model."""
    drivers: list[DriverOut]
    """Every way of reaching a model, in the order the lobby shows them."""
    personas: list[SeatPersonaOut]
    """Who sits in the bot seats, in seat order."""


class RoomCreatedOut(BaseModel):
    room_code: str
    game_id: str
    player_id: str
    token: str
    game: GameOut


class TurnOut(BaseModel):
    """One turn a model-driven seat played: what it was shown and what it answered."""

    version: int
    player_id: str
    driver: str
    source: str
    fallback_reason: str | None
    attempts: int
    duration_ms: float
    input_tokens: int
    output_tokens: int
    observation: dict[str, Any] | None
    exchanges: list[dict[str, Any]]

    @classmethod
    def from_record(cls, record: TurnRecord) -> TurnOut:
        return cls(
            version=record.version,
            player_id=record.player_id,
            driver=record.driver,
            source=record.source,
            fallback_reason=record.fallback_reason,
            attempts=record.attempts,
            duration_ms=record.duration_ms,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            observation=None if record.observation is None else dict(record.observation),
            exchanges=[dict(exchange) for exchange in record.exchanges],
        )


class ReplayOut(BaseModel):
    """A finished game with everything behind it, to be replayed step by step."""

    game: GameOut
    turns: list[TurnOut]


class ErrorOut(BaseModel):
    code: str
    message: str
