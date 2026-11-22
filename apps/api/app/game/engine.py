"""The single authority for Avalon state transitions.

Two pure functions do all the work:

- `apply_action(state, action)` decides. It validates an action against the
  rules and returns the new state together with the events that happened, or
  raises `RuleViolation` and changes nothing.
- `evolve(state, event)` applies one event. It never validates and never
  fails for an event the engine itself produced, so `replay` of a stored event
  log always rebuilds the same state.

Nothing here touches the network, a database, the clock or global randomness;
the only randomness comes from the seed inside `StartGame`.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from functools import reduce
from typing import Any

from app.game.actions import (
    Action,
    Assassinate,
    ProposeTeam,
    Speak,
    StartGame,
    VoteMission,
    VoteTeam,
)
from app.game.errors import ErrorCode, RuleViolation
from app.game.events import (
    AssassinationAttempted,
    AssassinationStarted,
    GameEvent,
    GameFinished,
    GameStarted,
    MissionCompleted,
    MissionStarted,
    MissionVoteCast,
    PlayerSpoke,
    TeamApproved,
    TeamProposed,
    TeamRejected,
    TeamVoteCast,
)
from app.game.rulesets import Alignment, Role, RuleSet
from app.game.state import (
    GameState,
    MissionOutcome,
    MissionState,
    MissionVote,
    Phase,
    PlayerState,
    Speech,
    TeamVote,
    TeamVoteRecord,
    WinReason,
)

SPEECH_LIMIT = 200
"""Characters in one speech, after whitespace is collapsed."""
MAX_SUSPECTS = 3


def clean_speech(text: str) -> str:
    """One line of printable text. What people type is shown to everyone at the table."""
    single_line = " ".join(text.split())
    return "".join(character for character in single_line if character.isprintable())


def new_game(
    *,
    game_id: str,
    ruleset: RuleSet,
    player_ids: Sequence[str],
    host_id: str,
) -> GameState:
    """Create a game in the lobby. Seats follow the order of `player_ids`."""
    ids = tuple(player_ids)
    if len(set(ids)) != len(ids):
        raise RuleViolation(ErrorCode.DUPLICATE_PLAYER, "Player ids must be unique.")
    if host_id not in ids:
        raise RuleViolation(
            ErrorCode.UNKNOWN_PLAYER, f"Host '{host_id}' is not one of the players."
        )

    return GameState(
        game_id=game_id,
        ruleset=ruleset,
        host_id=host_id,
        players=tuple(PlayerState(id=player_id, seat=seat) for seat, player_id in enumerate(ids)),
    )


def apply_action(state: GameState, action: Action) -> tuple[GameState, list[GameEvent]]:
    """Validate `action` and return the resulting state and events."""
    handler = _HANDLERS.get(type(action))
    if handler is None:
        raise TypeError(f"Unsupported action type: {type(action).__name__}")

    if action.expected_version is not None and action.expected_version != state.version:
        raise RuleViolation(
            ErrorCode.STALE_VERSION,
            f"Action was made for version {action.expected_version}, "
            f"but the game is at version {state.version}.",
        )

    actor = state.find_player(action.player_id)
    if actor is None:
        raise RuleViolation(
            ErrorCode.UNKNOWN_PLAYER, f"Player '{action.player_id}' is not in this game."
        )

    transition = _Transition(state)
    handler(transition, actor, action)
    return transition.state, transition.events


def replay(initial: GameState, events: Iterable[GameEvent]) -> GameState:
    """Rebuild a state by applying stored events to the lobby state they started from."""
    return reduce(evolve, events, initial)


def evolve(state: GameState, event: GameEvent) -> GameState:
    """Apply one event. Each event advances the version by exactly one."""
    return replace(_apply_event(state, event), version=state.version + 1)


# --- Deciding: action -> events ---------------------------------------------


class _Transition:
    """Collects the events of one action, keeping the state in step with them."""

    def __init__(self, state: GameState) -> None:
        self.state = state
        self.events: list[GameEvent] = []

    def emit(self, event: GameEvent) -> None:
        self.state = evolve(self.state, event)
        self.events.append(event)


def _start_game(transition: _Transition, actor: PlayerState, action: StartGame) -> None:
    state = transition.state
    _require_phase(state, Phase.LOBBY)
    if actor.id != state.host_id:
        raise RuleViolation(ErrorCode.NOT_HOST, "Only the host can start the game.")

    rules = state.ruleset.for_players(len(state.players))

    rng = random.Random(action.seed)
    deck = list(rules.roles)
    rng.shuffle(deck)
    first_leader_id = rng.choice(state.player_ids)

    transition.emit(
        GameStarted(seed=action.seed, roles=tuple(zip(state.player_ids, deck, strict=True)))
    )
    transition.emit(MissionStarted(mission_number=1, leader_id=first_leader_id))


def _propose_team(transition: _Transition, actor: PlayerState, action: ProposeTeam) -> None:
    state = transition.state
    _require_phase(state, Phase.TEAM_PROPOSAL)
    if actor.id != state.leader_id:
        raise RuleViolation(ErrorCode.NOT_LEADER, "Only the current leader can propose a team.")

    mission = state.current_mission
    proposed = set(action.team)
    if len(proposed) != len(action.team):
        raise RuleViolation(
            ErrorCode.DUPLICATE_TEAM_MEMBER, "A player can only be on the team once."
        )
    unknown = proposed - set(state.player_ids)
    if unknown:
        raise RuleViolation(
            ErrorCode.UNKNOWN_TEAM_MEMBER,
            f"Not players in this game: {', '.join(sorted(unknown))}.",
        )
    if len(proposed) != mission.team_size:
        raise RuleViolation(
            ErrorCode.WRONG_TEAM_SIZE,
            f"Mission {mission.number} needs {mission.team_size} players, got {len(proposed)}.",
        )

    transition.emit(
        TeamProposed(
            mission_number=mission.number,
            proposal_number=state.proposal_number,
            leader_id=actor.id,
            team=_in_seat_order(state, proposed),
        )
    )


def _speak(transition: _Transition, actor: PlayerState, action: Speak) -> None:
    state = transition.state
    _require_phase(state, Phase.DISCUSSION)
    if actor.id != state.next_speaker_id:
        raise RuleViolation(ErrorCode.NOT_YOUR_TURN_TO_SPEAK, "It is not your turn to speak yet.")

    text = clean_speech(action.text)
    if len(text) > SPEECH_LIMIT:
        raise RuleViolation(
            ErrorCode.SPEECH_TOO_LONG, f"A speech is at most {SPEECH_LIMIT} characters."
        )
    suspects = set(action.suspects)
    allowed = set(state.player_ids) - {actor.id}
    if (
        len(suspects) != len(action.suspects)
        or len(suspects) > MAX_SUSPECTS
        or not suspects <= allowed
    ):
        raise RuleViolation(
            ErrorCode.INVALID_SUSPECT,
            f"Name at most {MAX_SUSPECTS} other players, each once.",
        )

    transition.emit(
        PlayerSpoke(
            mission_number=state.current_mission.number,
            proposal_number=state.proposal_number,
            player_id=actor.id,
            text=text,
            suspects=_in_seat_order(state, suspects),
        )
    )


def _vote_team(transition: _Transition, actor: PlayerState, action: VoteTeam) -> None:
    state = transition.state
    _require_phase(state, Phase.TEAM_VOTE)
    if any(vote.player_id == actor.id for vote in state.team_votes):
        raise RuleViolation(ErrorCode.ALREADY_VOTED, "You have already voted on this team.")

    transition.emit(TeamVoteCast(player_id=actor.id, approve=action.approve))

    state = transition.state
    if len(state.team_votes) < len(state.players):
        return

    approvals = _in_seat_order(state, {v.player_id for v in state.team_votes if v.approve})
    rejections = _in_seat_order(state, {v.player_id for v in state.team_votes if not v.approve})
    mission_number = state.current_mission.number
    proposal_number = state.proposal_number

    # A tie is a rejection: the team needs a strict majority.
    if len(approvals) > len(rejections):
        transition.emit(
            TeamApproved(
                mission_number=mission_number,
                proposal_number=proposal_number,
                approvals=approvals,
                rejections=rejections,
            )
        )
        return

    transition.emit(
        TeamRejected(
            mission_number=mission_number,
            proposal_number=proposal_number,
            approvals=approvals,
            rejections=rejections,
            next_leader_id=_next_leader_id(state),
        )
    )
    if transition.state.rejected_proposals >= state.ruleset.max_rejected_proposals:
        transition.emit(GameFinished(winner=Alignment.EVIL, reason=WinReason.PROPOSALS_REJECTED))


def _vote_mission(transition: _Transition, actor: PlayerState, action: VoteMission) -> None:
    state = transition.state
    _require_phase(state, Phase.MISSION_VOTE)
    mission = state.current_mission
    if actor.id not in mission.team:
        raise RuleViolation(ErrorCode.NOT_ON_TEAM, "Only players on the mission team can vote.")
    if any(vote.player_id == actor.id for vote in state.mission_votes):
        raise RuleViolation(ErrorCode.ALREADY_VOTED, "You have already played this mission.")
    if not action.success and _alignment(actor) is Alignment.GOOD:
        raise RuleViolation(
            ErrorCode.GOOD_MUST_SUCCEED, "Good players must play success on a mission."
        )

    transition.emit(MissionVoteCast(player_id=actor.id, success=action.success))

    state = transition.state
    if len(state.mission_votes) < len(mission.team):
        return

    fail_votes = sum(not vote.success for vote in state.mission_votes)
    outcome = (
        MissionOutcome.FAIL if fail_votes >= mission.fails_required else MissionOutcome.SUCCESS
    )
    next_leader_id = _next_leader_id(state)
    transition.emit(
        MissionCompleted(mission_number=mission.number, fail_votes=fail_votes, outcome=outcome)
    )

    state = transition.state
    ruleset = state.ruleset
    if state.failed_missions >= ruleset.missions_to_win:
        transition.emit(GameFinished(winner=Alignment.EVIL, reason=WinReason.MISSIONS_FAILED))
    elif state.successful_missions < ruleset.missions_to_win:
        transition.emit(MissionStarted(mission_number=mission.number + 1, leader_id=next_leader_id))
    elif ruleset.assassination_enabled:
        transition.emit(AssassinationStarted(assassin_id=_assassin(state).id))
    else:
        transition.emit(GameFinished(winner=Alignment.GOOD, reason=WinReason.MISSIONS_SUCCEEDED))


def _assassinate(transition: _Transition, actor: PlayerState, action: Assassinate) -> None:
    state = transition.state
    _require_phase(state, Phase.ASSASSINATION)
    if actor.role is not Role.ASSASSIN:
        raise RuleViolation(ErrorCode.NOT_ASSASSIN, "Only the Assassin can choose a target.")

    target = state.find_player(action.target_id)
    if target is None or target.id == actor.id:
        raise RuleViolation(ErrorCode.INVALID_TARGET, "The target must be another player.")

    transition.emit(AssassinationAttempted(assassin_id=actor.id, target_id=target.id))
    if target.role is Role.MERLIN:
        transition.emit(GameFinished(winner=Alignment.EVIL, reason=WinReason.MERLIN_ASSASSINATED))
    else:
        transition.emit(GameFinished(winner=Alignment.GOOD, reason=WinReason.MERLIN_SURVIVED))


_HANDLERS: dict[type, Callable[[_Transition, PlayerState, Any], None]] = {
    StartGame: _start_game,
    ProposeTeam: _propose_team,
    VoteTeam: _vote_team,
    Speak: _speak,
    VoteMission: _vote_mission,
    Assassinate: _assassinate,
}


def _require_phase(state: GameState, expected: Phase) -> None:
    if state.phase is not expected:
        raise RuleViolation(
            ErrorCode.WRONG_PHASE,
            f"This action needs phase '{expected}', but the game is in '{state.phase}'.",
        )


def _alignment(player: PlayerState) -> Alignment:
    assert player.role is not None, "roles are assigned when the game starts"
    return player.role.alignment


def _assassin(state: GameState) -> PlayerState:
    return next(player for player in state.players if player.role is Role.ASSASSIN)


def _next_leader_id(state: GameState) -> str:
    """The leader token passes to the next seat, wrapping around the table."""
    current = next(player for player in state.players if player.id == state.leader_id)
    return state.players[(current.seat + 1) % len(state.players)].id


def _in_seat_order(state: GameState, player_ids: set[str]) -> tuple[str, ...]:
    return tuple(player.id for player in state.players if player.id in player_ids)


# --- Evolving: event -> state ------------------------------------------------


def _apply_event(state: GameState, event: GameEvent) -> GameState:
    match event:
        case GameStarted():
            rules = state.ruleset.for_players(len(state.players))
            roles = dict(event.roles)
            return replace(
                state,
                phase=Phase.TEAM_PROPOSAL,
                players=tuple(replace(player, role=roles[player.id]) for player in state.players),
                missions=tuple(
                    MissionState(number=number, team_size=team_size, fails_required=fails)
                    for number, (team_size, fails) in enumerate(
                        zip(rules.team_sizes, rules.fail_thresholds, strict=True), start=1
                    )
                ),
            )
        case MissionStarted():
            return replace(
                state,
                phase=Phase.TEAM_PROPOSAL,
                mission_index=event.mission_number - 1,
                leader_id=event.leader_id,
                rejected_proposals=0,
            )
        case TeamProposed():
            return replace(state, phase=Phase.DISCUSSION, proposed_team=event.team, speeches=())
        case PlayerSpoke():
            speech = Speech(player_id=event.player_id, text=event.text, suspects=event.suspects)
            speeches = (*state.speeches, speech)
            # Once everyone has spoken the table votes.
            everyone = len(speeches) == len(state.players)
            return replace(
                state,
                speeches=speeches,
                phase=Phase.TEAM_VOTE if everyone else Phase.DISCUSSION,
            )
        case TeamVoteCast():
            team_vote = TeamVote(player_id=event.player_id, approve=event.approve)
            return replace(state, team_votes=(*state.team_votes, team_vote))
        case TeamApproved():
            return replace(
                _update_current_mission(state, team=state.proposed_team),
                phase=Phase.MISSION_VOTE,
                proposed_team=(),
                team_votes=(),
                last_team_vote=_vote_record(state, event, approved=True),
            )
        case TeamRejected():
            return replace(
                state,
                phase=Phase.TEAM_PROPOSAL,
                proposed_team=(),
                team_votes=(),
                rejected_proposals=state.rejected_proposals + 1,
                leader_id=event.next_leader_id,
                last_team_vote=_vote_record(state, event, approved=False),
            )
        case MissionVoteCast():
            mission_vote = MissionVote(player_id=event.player_id, success=event.success)
            return replace(state, mission_votes=(*state.mission_votes, mission_vote))
        case MissionCompleted():
            return replace(
                _update_current_mission(state, fail_votes=event.fail_votes, outcome=event.outcome),
                mission_votes=(),
            )
        case AssassinationStarted():
            return replace(state, phase=Phase.ASSASSINATION)
        case AssassinationAttempted():
            return replace(state, assassination_target_id=event.target_id)
        case GameFinished():
            return replace(
                state, phase=Phase.FINISHED, winner=event.winner, win_reason=event.reason
            )
        case _:
            raise TypeError(f"Unsupported event type: {type(event).__name__}")


def _vote_record(
    state: GameState, event: TeamApproved | TeamRejected, *, approved: bool
) -> TeamVoteRecord:
    return TeamVoteRecord(
        mission_number=event.mission_number,
        proposal_number=event.proposal_number,
        team=state.proposed_team,
        approvals=event.approvals,
        rejections=event.rejections,
        approved=approved,
    )


def _update_current_mission(state: GameState, **changes: Any) -> GameState:
    missions = list(state.missions)
    missions[state.mission_index] = replace(state.current_mission, **changes)
    return replace(state, missions=tuple(missions))
