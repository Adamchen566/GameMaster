"""A bot that reads the table, says what it thinks and acts on it.

It replaces the random seat-filler in real games. Like every player it is given
its own `PlayerView` and the public log, nothing else. From those it keeps a
suspicion score per player:

- being on a mission that failed is the strongest evidence;
- approving a team that then failed counts a little;
- being on a mission that succeeded counts in a player's favour;
- being named as a suspect in someone's speech counts a little.

A good bot proposes the players it suspects least, speaks against teams that
contain someone it suspects and votes the way it spoke. An evil bot runs the
same reasoning on public evidence so that it sounds like a good one, but it
shields its partners, wants one of them on every team, and decides for itself
when to play a fail card. Merlin acts on what it knows and gives public reasons
only; the Assassin looks for the player who behaved as if they knew.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations

from app.game.actions import Action, Assassinate, ProposeTeam, Speak, VoteMission, VoteTeam
from app.game.public_log import PublicEntry
from app.game.rulesets import Alignment
from app.game.state import MissionOutcome
from app.game.views import Knowledge, LegalAction, PlayerView
from app.gm.templates import Language

FAILED_MISSION_WEIGHT = 2.0
BACKED_FAILED_TEAM_WEIGHT = 0.3
CLEAN_MISSION_CREDIT = 0.4
ACCUSATION_WEIGHT = 0.25
DISTRUST_MARGIN = 0.15
"""How far above the starting odds a player must be before a bot keeps them off a team."""
FAIL_RATE = 0.85
"""How often the bot assumes an evil player on a mission plays a fail."""
SAW_THROUGH = 1.15
WAVED_ON = 1.2
HONEST_HIT = 1.3
HONEST_MISS = 0.85
VOICED_THRESHOLD = 0.5
"""From this score on, a bot names the player in its speech."""
MERLIN_COVER_RATE = 0.45
IDLE_DOUBT_RATE = 0.12
EVIL_BLEND_IN_RATE = 0.25
EVIL_FRAME_RATE = 0.35


@dataclass
class Table:
    """What the public record says about each player."""

    suspicion: dict[str, float]
    reasons: dict[str, list[str]] = field(default_factory=dict)
    """Why, as reason keys such as ("failed_mission", 2)."""
    teams: dict[tuple[int, int], tuple[str, ...]] = field(default_factory=dict)
    votes: list[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = field(
        default_factory=list
    )
    """(team, approvals, rejections) for every finished team vote."""
    accusations: list[tuple[str, str]] = field(default_factory=list)
    """(accuser, accused), each pair once."""


def _ids(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def read_table(
    view: PlayerView, history: Sequence[PublicEntry], *, innocent: str | None = None
) -> Table:
    """Score everyone from public events. `innocent` is a player known not to have failed."""
    table = Table(suspicion={player.id: 0.0 for player in view.players})
    reasons: dict[str, list[str]] = {player.id: [] for player in view.players}
    approved: dict[int, tuple[tuple[str, ...], tuple[str, ...]]] = {}

    def blame(player_id: str, amount: float, reason: str) -> None:
        if player_id in table.suspicion:
            table.suspicion[player_id] += amount
            if reason not in reasons[player_id]:
                reasons[player_id].append(reason)

    for entry in history:
        data = entry.data
        match entry.kind:
            case "team_proposed":
                key = (int(str(data["mission"])), int(str(data["proposal"])))
                table.teams[key] = _ids(data["team"])
            case "team_vote":
                key = (int(str(data["mission"])), int(str(data["proposal"])))
                team = table.teams.get(key, ())
                approvals, rejections = _ids(data["approvals"]), _ids(data["rejections"])
                table.votes.append((team, approvals, rejections))
                if data["approved"]:
                    approved[key[0]] = (team, approvals)
            case "mission_result":
                number = int(str(data["mission"]))
                team, approvals = approved.get(number, ((), ()))
                if data["outcome"] == MissionOutcome.FAIL.value:
                    suspects = [member for member in team if member != innocent]
                    fails = int(str(data["fail_votes"]))
                    for member in suspects:
                        share = FAILED_MISSION_WEIGHT * fails / len(suspects)
                        blame(member, share, f"failed_mission:{number}")
                    for voter in approvals:
                        if voter not in team:
                            blame(voter, BACKED_FAILED_TEAM_WEIGHT, f"backed_failed_team:{number}")
                else:
                    for member in team:
                        table.suspicion[member] -= CLEAN_MISSION_CREDIT
            case "speech":
                accuser = str(data["player"])
                for accused in _ids(data["suspects"]):
                    if (accuser, accused) not in table.accusations:
                        table.accusations.append((accuser, accused))
                        blame(accused, ACCUSATION_WEIGHT, "accused")
            case _:
                pass

    table.reasons = reasons
    return table


def chance_of_evil(view: PlayerView, table: Table, *, innocent: str) -> dict[str, float]:
    """How likely each other player is evil, given what has happened in public.

    Every way of dealing the evil roles among the other players is weighed by how
    well it explains the mission results, the votes and the accusations; a
    player's chance is the share of that weight in which they are evil.
    """
    others = [player.id for player in view.players if player.id != innocent]
    evil_count = view.evil_count
    finished = [mission for mission in view.missions if mission.outcome is not None]
    totals = dict.fromkeys(others, 0.0)
    weight_sum = 0.0

    for dealt in combinations(others, evil_count):
        evil = frozenset(dealt)
        weight = 1.0
        for mission in finished:
            on_team = sum(member in evil for member in mission.team)
            fails = mission.fail_votes or 0
            if on_team < fails:
                weight = 0.0
                break
            # An evil player on a mission usually, not always, plays a fail.
            weight *= math.comb(on_team, fails) * FAIL_RATE**fails
            weight *= (1 - FAIL_RATE) ** (on_team - fails)
        if weight == 0.0:
            continue
        for team, approvals, rejections in table.votes:
            if any(member in evil for member in team):
                # Good players who saw through a bad team, evil ones who waved it on.
                weight *= SAW_THROUGH ** sum(voter not in evil for voter in rejections)
                weight *= WAVED_ON ** sum(voter in evil for voter in approvals)
        for accuser, accused in table.accusations:
            if accuser not in evil:
                weight *= HONEST_HIT if accused in evil else HONEST_MISS
        weight_sum += weight
        for player_id in evil:
            totals[player_id] += weight

    if weight_sum == 0.0:
        # Cannot happen with honest events; fall back to knowing nothing.
        return dict.fromkeys(others, evil_count / len(others))
    return {player_id: total / weight_sum for player_id, total in totals.items()}


@dataclass(frozen=True)
class Stance:
    approve: bool
    worry: str | None
    """The team member the bot gives as its reason for rejecting, if it has one."""
    voiced: tuple[str, ...]
    """Players the bot names as suspects in its speech."""


class _Mind:
    """One bot's reading of the game from its own seat."""

    def __init__(self, view: PlayerView, history: Sequence[PublicEntry], salt: str) -> None:
        self.view = view
        self.me = view.you_id
        you = next(player for player in view.players if player.id == view.you_id)
        self.evil = you.alignment is Alignment.EVIL
        self.known_evil = frozenset(
            player.id for player in view.players if player.seen_as is Knowledge.EVIL
        )
        """Merlin's knowledge, or an evil player's partners."""
        self.public = read_table(view, history)
        # A good player knows one more thing than the table: it is not evil itself.
        self.odds = {} if self.evil else chance_of_evil(view, self.public, innocent=self.me)
        self.starting_odds = view.evil_count / (len(view.players) - 1)
        mission, proposal = view.current_mission_number or 0, view.proposal_number or 0
        # Anything that must agree between a speech and the vote that follows it.
        # Drawn up front, so the vote cannot drift from the speech as more is said.
        steady = random.Random(f"{salt}:{self.me}:{mission}:{proposal}")
        self.blend_in = steady.random() < EVIL_BLEND_IN_RATE
        self.take_cover = steady.random() < MERLIN_COVER_RATE
        self.frame = steady.random() < EVIL_FRAME_RATE
        self.frame_pick = steady.random()
        self.idle_doubt = steady.random() < IDLE_DOUBT_RATE
        # Picks the wording only, so it never changes what the bot decides.
        self.voice = random.Random(f"{salt}:{self.me}:{mission}:{proposal}:voice")

    # --- What this seat believes -------------------------------------------------

    def score(self, player_id: str) -> float:
        if player_id == self.me:
            return -100.0
        if self.evil:
            # Partners are fine by me; in public I hold them to the same record as anyone.
            return self.public.suspicion[player_id]
        if player_id in self.known_evil:
            return 100.0
        return self.odds[player_id]

    def distrusts(self, player_id: str) -> bool:
        if player_id in self.known_evil:
            return True
        return self.odds[player_id] >= self.starting_odds + DISTRUST_MARGIN

    def current_mission(self) -> tuple[int, int]:
        """`(team_size, fails_required)` of the mission on the table."""
        mission = next(
            m for m in self.view.missions if m.number == self.view.current_mission_number
        )
        return mission.team_size, mission.fails_required

    def failed_missions(self) -> int:
        return sum(mission.outcome is MissionOutcome.FAIL for mission in self.view.missions)

    # --- Decisions -----------------------------------------------------------------

    def pick_team(self, legal: LegalAction, rng: random.Random) -> tuple[str, ...]:
        size, fails_required = self.current_mission()
        others = [target for target in legal.targets if target != self.me]
        rng.shuffle(others)
        others.sort(key=self.score)

        if not self.evil:
            return (self.me, *others[: size - 1])

        # One of us is enough for most missions; more would look crowded.
        partners = [pid for pid in others if pid in self.known_evil]
        outsiders = [pid for pid in others if pid not in self.known_evil]
        extra = partners[: fails_required - 1]
        return (self.me, *extra, *outsiders[: size - 1 - len(extra)])

    def stance(self, team: Sequence[str]) -> Stance:
        view = self.view
        last_chance = view.proposal_number == view.max_rejected_proposals
        voiced = self._voiced()
        members = [member for member in team if member != self.me]

        if self.evil:
            ours = sum(member in self.known_evil or member == self.me for member in team)
            _, fails_required = self.current_mission()
            if ours >= fails_required:
                return Stance(approve=True, worry=None, voiced=voiced)
            if not last_chance and self.blend_in:
                return Stance(approve=True, worry=None, voiced=voiced)
            # Reject a clean team and give the most plausible public reason for it.
            outsiders = [member for member in members if member not in self.known_evil]
            scapegoat = max(outsiders, key=lambda pid: self.public.suspicion[pid], default=None)
            return Stance(approve=False, worry=scapegoat, voiced=voiced)

        worries = sorted((m for m in members if self.distrusts(m)), key=self.score, reverse=True)
        if last_chance:
            # Five rejections in a row lose the game, so the last proposal goes through.
            return Stance(approve=True, worry=None, voiced=voiced)
        if not worries:
            # Now and then a player holds out for a team they are on. It also means a
            # rejection without evidence does not single out the one who knows more.
            holds_out = self.idle_doubt and self.me not in team
            return Stance(approve=not holds_out, worry=None, voiced=voiced)
        explainable = [w for w in worries if self.public.suspicion[w] >= VOICED_THRESHOLD]
        if not explainable:
            # Only Merlin gets here: it knows, but the table has seen nothing yet.
            first_mission = not any(m.outcome is not None for m in self.view.missions)
            if first_mission or (self.failed_missions() < 2 and self.take_cover):
                return Stance(approve=True, worry=None, voiced=voiced)
            return Stance(approve=False, worry=None, voiced=voiced)
        return Stance(approve=False, worry=explainable[0], voiced=voiced)

    def _voiced(self) -> tuple[str, ...]:
        """Whom to name out loud. Only what the public record can back up."""
        candidates = [
            player.id
            for player in self.view.players
            if player.id != self.me
            and not (self.evil and player.id in self.known_evil)
            and self.public.suspicion[player.id] >= VOICED_THRESHOLD
        ]
        candidates.sort(key=lambda pid: self.public.suspicion[pid], reverse=True)
        if not candidates and self.evil and self.failed_missions() > 0:
            outsiders = [
                player.id
                for player in self.view.players
                if player.id != self.me and player.id not in self.known_evil
            ]
            if outsiders and self.frame:
                candidates = [outsiders[int(self.frame_pick * len(outsiders))]]
        return tuple(candidates[:2])

    def plays_fail(self, legal: LegalAction, rng: random.Random) -> bool:
        if not legal.can_fail:
            return False
        size, fails_required = self.current_mission()
        if self.failed_missions() == self.view.missions_to_win - 1 or fails_required > 1:
            return True
        if self.view.current_mission_number == 1 and size <= 2:
            # A fail on a two-player first mission points straight at the pair.
            return rng.random() < 0.4
        return rng.random() < 0.85

    def guess_merlin(self, legal: LegalAction, rng: random.Random) -> str:
        """Merlin is the good player who kept turning out to be right."""
        ours = self.known_evil | {self.me}
        targets = [target for target in legal.targets if target not in ours] or list(legal.targets)
        insight = {target: 0.0 for target in targets}
        for team, approvals, rejections in self.public.votes:
            tainted = any(member in ours for member in team)
            for player_id in rejections if tainted else approvals:
                if player_id in insight:
                    insight[player_id] += 1.0 if tainted else 0.5
        for accuser, accused in self.public.accusations:
            if accuser in insight:
                insight[accuser] += 1.0 if accused in ours else -0.5
        best = max(insight.values())
        return rng.choice([target for target, value in insight.items() if value == best])


# --- Speaking ---------------------------------------------------------------------

_LINES: dict[str, dict[str, tuple[str, ...]]] = {
    "lead_blind": {
        "zh": (
            "第一轮没有任何信息，我先选 {team} 试一队。",
            "现在谁都看不清，我带 {team} 出发，拿结果说话。",
            "先试一队：{team}。就算失败，我们也有线索了。",
            "没有依据可言，我选 {team}，大家别太紧张。",
        ),
        "en": (
            "There is nothing to go on yet, so I am trying {team}.",
            "Nobody can see anything yet. I will take {team} and let the result speak.",
            "A first try: {team}. If it fails, at least we learn something.",
        ),
    },
    "lead": {
        "zh": (
            "我选 {team}，他们是目前我最放心的人。",
            "按目前的记录，{team} 最干净，我就带他们。",
            "这一队我选 {team}，有疑问的人我都没带。",
            "我带 {team}。看了前面几轮，这是我能凑出的最稳的一队。",
        ),
        "en": (
            "I am taking {team}: the players I trust most right now.",
            "On the record so far, {team} look cleanest, so they go.",
            "{team}. I left out everyone I have doubts about.",
        ),
    },
    "approve_blind": {
        "zh": (
            "还没有任何线索，我先让这队出发，看结果再说。",
            "第一队没什么好挑的，我赞成，看看结果。",
            "现在反对也说不出理由，我投赞成。",
            "先让他们去吧，结果出来再分析。",
        ),
        "en": (
            "Nothing to judge by yet. I will let this team go and see what happens.",
            "There is nothing to pick at in a first team. I approve.",
            "I have no reason to object yet, so I approve.",
        ),
    },
    "approve": {
        "zh": (
            "这支队伍我能接受，会投赞成。",
            "这一队看着没问题，我支持。",
            "队里没有我怀疑的人，赞成。",
            "我没意见，让他们出发吧。",
            "这队我放心，投赞成。",
        ),
        "en": (
            "I can live with this team. I will approve.",
            "This team looks fine to me. I support it.",
            "Nobody I suspect is on it. Approve.",
        ),
    },
    "reject_because": {
        "zh": (
            "我会反对：队里有 {who}，{why}。",
            "{who} 在队里我不放心，{why}，我投反对。",
            "这队我不同意，{who} {why}，不能再让这个人上车。",
            "换掉 {who} 我就赞成。{who} {why}。",
        ),
        "en": (
            "I will reject: {who} is on it and {why}.",
            "Not with {who} on it: {who} {why}. I reject.",
            "Swap out {who} and I will approve. {who} {why}.",
        ),
    },
    "reject": {
        "zh": (
            "这支队伍我还不放心，想再看一轮，会投反对。",
            "说不上哪里不对，但这队我想先反对一次。",
            "我先投反对，想听听下一位队长怎么排。",
            "这一队我心里没底，反对。",
        ),
        "en": (
            "I am not comfortable with this team yet. I will reject.",
            "I cannot say exactly why, but I want to turn this one down.",
            "I will reject and see how the next leader builds a team.",
        ),
    },
    "suspect": {
        "zh": (
            "我怀疑 {who}。",
            "另外我在盯着 {who}。",
            "顺便说一句，{who} 让我很在意。",
            "我目前最怀疑的是 {who}。",
        ),
        "en": (
            "I suspect {who}.",
            "I am also keeping an eye on {who}.",
            "And {who} worries me.",
        ),
    },
}
"""Ways of saying each stance. The seat and the proposal pick one, so a table does not echo."""


def _reason(key: str, language: Language) -> str:
    kind, _, number = key.partition(":")
    zh = language == "zh"
    match kind:
        case "failed_mission":
            return f"第 {number} 轮任务失败时在队里" if zh else f"was on failed mission {number}"
        case "backed_failed_team":
            return (
                f"投票支持了第 {number} 轮失败的队伍"
                if zh
                else f"voted for the team that failed mission {number}"
            )
        case _:
            return "被别人点过名" if zh else "has been named by others"


def _say(mind: _Mind, names: Mapping[str, str], language: Language) -> Speak:
    view, zh = mind.view, language == "zh"
    team = view.proposed_team
    stance = mind.stance(team)
    comma = "、" if zh else ", "

    def name(player_id: str) -> str:
        return names.get(player_id, player_id)

    def why(player_id: str) -> str:
        reasons = mind.public.reasons.get(player_id, [])
        if not reasons:
            return "我说不出证据，只是直觉" if zh else "no proof, only a feeling"
        return _reason(reasons[0], language)

    def line(kind: str, **values: str) -> str:
        options = _LINES[kind]["zh" if zh else "en"]
        return mind.voice.choice(options).format(**values)

    parts: list[str] = []
    if view.you_id == view.leader_id:
        chosen = comma.join(name(member) for member in team)
        parts.append(line("lead_blind" if not mind.public.votes else "lead", team=chosen))
    elif stance.approve and not mind.public.votes:
        parts.append(line("approve_blind"))
    elif stance.approve:
        parts.append(line("approve"))
    elif stance.worry is not None:
        worry = stance.worry
        parts.append(line("reject_because", who=name(worry), why=why(worry)))
    else:
        parts.append(line("reject"))

    others = [pid for pid in stance.voiced if pid != stance.worry]
    if others:
        listed = comma.join(
            f"{name(pid)}（{why(pid)}）" if zh else f"{name(pid)} ({why(pid)})" for pid in others
        )
        parts.append(line("suspect", who=listed))

    suspects = tuple(dict.fromkeys(pid for pid in (stance.worry, *stance.voiced) if pid))[:3]
    return Speak(
        player_id=view.you_id,
        text=("" if zh else " ").join(parts)[:200],
        suspects=suspects,
        expected_version=view.version,
    )


def choose_action(
    view: PlayerView,
    rng: random.Random,
    *,
    history: Sequence[PublicEntry] = (),
    names: Mapping[str, str] | None = None,
    language: Language = "zh",
    salt: str | None = None,
) -> Action:
    """Pick a legal action for `view.you_id`, with a spoken reason when it is time to talk.

    `salt` seeds the choices that must stay the same through one proposal (what the bot
    says and how it then votes). Pass the game's seed to make a game reproducible.
    """
    if not view.legal_actions:
        raise ValueError(f"Player '{view.you_id}' has nothing to do right now.")

    legal = view.legal_actions[0]
    mind = _Mind(view, history, salt if salt is not None else view.game_id)
    you, version = view.you_id, view.version
    match legal.type:
        case "propose_team":
            team = mind.pick_team(legal, rng)
            return ProposeTeam(player_id=you, team=team, expected_version=version)
        case "speak":
            return _say(mind, names or {}, language)
        case "vote_team":
            approve = you == view.leader_id or mind.stance(view.proposed_team).approve
            return VoteTeam(player_id=you, approve=approve, expected_version=version)
        case "vote_mission":
            fails = mind.plays_fail(legal, rng)
            return VoteMission(player_id=you, success=not fails, expected_version=version)
        case "assassinate":
            target = mind.guess_merlin(legal, rng)
            return Assassinate(player_id=you, target_id=target, expected_version=version)
        case other:
            # Starting the game is the host's decision, and the host is a human.
            raise ValueError(f"The table bot cannot perform '{other}'.")


def inner_thought(
    view: PlayerView,
    *,
    history: Sequence[PublicEntry] = (),
    names: Mapping[str, str] | None = None,
    language: Language = "zh",
    salt: str | None = None,
) -> str:
    """What the bot in this seat really believes right now, in one or two sentences.

    Unlike its speech this is not filtered for what is safe to say: it names the
    bot's side and what it knows. It is only ever shown to spectators and in the
    review after the game.
    """
    mind = _Mind(view, history, salt if salt is not None else view.game_id)
    zh = language == "zh"
    labels = names or {}

    def name(player_id: str) -> str:
        return labels.get(player_id, player_id)

    def listed(ids: Sequence[str]) -> str:
        return ("、" if zh else ", ").join(name(player_id) for player_id in ids)

    known = sorted(mind.known_evil)
    parts: list[str] = []
    if mind.evil:
        if known:
            parts.append(
                f"我是邪恶方，同伴是 {listed(known)}。"
                if zh
                else f"I am evil, with {listed(known)}."
            )
        else:
            parts.append("我是邪恶方。" if zh else "I am evil.")
    elif known:
        parts.append(
            f"我知道 {listed(known)} 是邪恶方，但不能说得太明显。"
            if zh
            else f"I know {listed(known)} are evil, but I must not make that obvious."
        )
    else:
        others = [player.id for player in view.players if player.id != mind.me]
        top = max(others, key=mind.score)
        if mind.odds[top] >= mind.starting_odds + DISTRUST_MARGIN:
            parts.append(
                f"我最怀疑 {name(top)}（{mind.odds[top]:.0%}）。"
                if zh
                else f"I suspect {name(top)} most ({mind.odds[top]:.0%})."
            )
        else:
            parts.append("还没有可靠的线索。" if zh else "No solid lead yet.")

    legal = view.legal_actions[0].type if view.legal_actions else ""
    if legal == "speak" and view.proposed_team:
        approve = mind.me == view.leader_id or mind.stance(view.proposed_team).approve
        on_team = [member for member in view.proposed_team if member in mind.known_evil]
        if mind.evil and on_team:
            parts.append(
                f"队里有同伴 {listed(on_team)}，我要让它通过。"
                if zh
                else f"{listed(on_team)} is on the team; I want it through."
            )
        elif approve:
            parts.append("这一队我会投赞成。" if zh else "I will approve this team.")
        else:
            parts.append("这一队我会投反对。" if zh else "I will reject this team.")
    return " ".join(parts) if not zh else "".join(parts)
