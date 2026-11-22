"""Play a whole game with random legal moves and print it.

    python -m app.game.simulate --players 7 --seed 42

This is a development tool, not an AI player: it reads the full secret state
to decide who may play a fail card. The same arguments always print the same
game, which makes it handy for checking determinism by eye.
"""

from __future__ import annotations

import argparse
import random
from collections.abc import Sequence
from dataclasses import dataclass

from app.game.actions import Action, Assassinate, ProposeTeam, StartGame, VoteMission, VoteTeam
from app.game.engine import apply_action, new_game
from app.game.events import (
    AssassinationAttempted,
    AssassinationStarted,
    GameEvent,
    GameFinished,
    GameStarted,
    MissionCompleted,
    MissionStarted,
    MissionVoteCast,
    TeamApproved,
    TeamProposed,
    TeamRejected,
    TeamVoteCast,
)
from app.game.rulesets import OFFICIAL, Alignment, Role, RuleSet
from app.game.state import GameState, Phase

APPROVAL_RATE = 0.6
EVIL_FAIL_RATE = 0.5


@dataclass(frozen=True, slots=True)
class SimulatedGame:
    initial: GameState
    final: GameState
    events: tuple[GameEvent, ...]


def next_action(state: GameState, rng: random.Random) -> Action:
    """A random legal action for whoever has to act next."""
    match state.phase:
        case Phase.TEAM_PROPOSAL:
            assert state.leader_id is not None
            team = rng.sample(state.player_ids, state.current_mission.team_size)
            return ProposeTeam(player_id=state.leader_id, team=tuple(team))
        case Phase.TEAM_VOTE:
            voted = {vote.player_id for vote in state.team_votes}
            voter_id = next(pid for pid in state.player_ids if pid not in voted)
            return VoteTeam(player_id=voter_id, approve=rng.random() < APPROVAL_RATE)
        case Phase.MISSION_VOTE:
            voted = {vote.player_id for vote in state.mission_votes}
            member_id = next(pid for pid in state.current_mission.team if pid not in voted)
            member = state.find_player(member_id)
            assert member is not None and member.role is not None
            is_evil = member.role.alignment is Alignment.EVIL
            fails = is_evil and rng.random() < EVIL_FAIL_RATE
            return VoteMission(player_id=member_id, success=not fails)
        case Phase.ASSASSINATION:
            assassin = next(player for player in state.players if player.role is Role.ASSASSIN)
            targets = [pid for pid in state.player_ids if pid != assassin.id]
            return Assassinate(player_id=assassin.id, target_id=rng.choice(targets))
        case _:
            raise ValueError(f"No player can act in phase '{state.phase}'.")


def play_random_game(*, player_count: int, seed: int, ruleset: RuleSet = OFFICIAL) -> SimulatedGame:
    rng = random.Random(seed)
    player_ids = tuple(f"p{number}" for number in range(1, player_count + 1))
    initial = new_game(
        game_id=f"sim-{player_count}-{seed}",
        ruleset=ruleset,
        player_ids=player_ids,
        host_id=player_ids[0],
    )

    start = StartGame(player_id=player_ids[0], seed=rng.getrandbits(32))
    state, events = apply_action(initial, start)
    while state.phase is not Phase.FINISHED:
        state, new_events = apply_action(state, next_action(state, rng))
        events.extend(new_events)

    return SimulatedGame(initial=initial, final=state, events=tuple(events))


def format_event(event: GameEvent) -> str:
    match event:
        case GameStarted():
            roles = ", ".join(f"{player_id}={role}" for player_id, role in event.roles)
            return f"GameStarted           {roles}"
        case MissionStarted():
            return f"MissionStarted        mission {event.mission_number}, leader {event.leader_id}"
        case TeamProposed():
            return (
                f"TeamProposed          mission {event.mission_number} "
                f"proposal {event.proposal_number}: {event.leader_id} proposes "
                f"[{', '.join(event.team)}]"
            )
        case TeamVoteCast():
            return f"TeamVoteCast          {event.player_id} {_approve(event.approve)}"
        case TeamApproved():
            return (
                f"TeamApproved          {len(event.approvals)} approve, "
                f"{len(event.rejections)} reject"
            )
        case TeamRejected():
            return (
                f"TeamRejected          {len(event.approvals)} approve, "
                f"{len(event.rejections)} reject; leader passes to {event.next_leader_id}"
            )
        case MissionVoteCast():
            card = "success" if event.success else "fail"
            return f"MissionVoteCast       {event.player_id} plays {card}"
        case MissionCompleted():
            return (
                f"MissionCompleted      mission {event.mission_number}: {event.outcome} "
                f"({event.fail_votes} fail)"
            )
        case AssassinationStarted():
            return f"AssassinationStarted  {event.assassin_id} must name Merlin"
        case AssassinationAttempted():
            return f"AssassinationAttempted {event.assassin_id} targets {event.target_id}"
        case GameFinished():
            return f"GameFinished          {event.winner} wins ({event.reason})"
        case _:
            raise TypeError(f"Unsupported event type: {type(event).__name__}")


def _approve(approve: bool) -> str:
    return "approves" if approve else "rejects"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play one random Avalon game and print it.")
    parser.add_argument("--players", type=int, default=5, help="number of players (default: 5)")
    parser.add_argument("--seed", type=int, default=0, help="random seed (default: 0)")
    args = parser.parse_args(argv)

    game = play_random_game(player_count=args.players, seed=args.seed)

    print(f"Rule set: {game.final.ruleset.id}, players: {args.players}, seed: {args.seed}")
    for version, event in enumerate(game.events, start=1):
        print(f"{version:>4}  {format_event(event)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
