"""A bot that plays random legal moves.

It is the seat-filler for single-player games and, later, the fallback when a
model-driven player times out. It receives a `PlayerView` and nothing else, so
it knows exactly what a human in that seat would know.
"""

from __future__ import annotations

import random

from app.game.actions import Action, Assassinate, ProposeTeam, VoteMission, VoteTeam
from app.game.views import Knowledge, PlayerView

APPROVAL_RATE = 0.6
EVIL_FAIL_RATE = 0.8


def _plausible_merlins(view: PlayerView, targets: tuple[str, ...]) -> tuple[str, ...]:
    """Skip players the Assassin already knows are evil; they cannot be Merlin."""
    known_evil = {player.id for player in view.players if player.seen_as is Knowledge.EVIL}
    return tuple(target for target in targets if target not in known_evil) or targets


def choose_action(view: PlayerView, rng: random.Random) -> Action:
    """Pick one of the actions the view says are legal."""
    if not view.legal_actions:
        raise ValueError(f"Player '{view.you_id}' has nothing to do right now.")

    legal = view.legal_actions[0]
    match legal.type:
        case "propose_team":
            assert legal.team_size is not None
            team = tuple(rng.sample(legal.targets, legal.team_size))
            return ProposeTeam(player_id=view.you_id, team=team, expected_version=view.version)
        case "vote_team":
            approve = rng.random() < APPROVAL_RATE
            return VoteTeam(player_id=view.you_id, approve=approve, expected_version=view.version)
        case "vote_mission":
            fails = legal.can_fail and rng.random() < EVIL_FAIL_RATE
            return VoteMission(
                player_id=view.you_id, success=not fails, expected_version=view.version
            )
        case "assassinate":
            return Assassinate(
                player_id=view.you_id,
                target_id=rng.choice(_plausible_merlins(view, legal.targets)),
                expected_version=view.version,
            )
        case _:
            # Starting the game is the host's decision, and the host is a human.
            raise ValueError(f"The fallback bot cannot perform '{legal.type}'.")
