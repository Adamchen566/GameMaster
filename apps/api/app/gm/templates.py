"""The game master's deterministic voice, in Chinese and English.

Every public event has a fixed sentence here. It is what players see when no
model is configured, when the model is slow or wrong, and it is always shown
as the statement of fact next to anything a model writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from app.game.public_log import PublicEntry

Language = Literal["zh", "en"]
Tone = Literal["neutral", "tense", "triumphant", "ominous"]
RuleHint = Literal[
    "none",
    "team_vote_majority",
    "rejection_limit",
    "double_fail_mission",
    "mission_cards",
    "assassination",
]

LANGUAGES: tuple[Language, ...] = ("zh", "en")
TONES: tuple[Tone, ...] = ("neutral", "tense", "triumphant", "ominous")
RULE_HINTS: tuple[RuleHint, ...] = (
    "none",
    "team_vote_majority",
    "rejection_limit",
    "double_fail_mission",
    "mission_cards",
    "assassination",
)

# The narrator is never told a role, so while a game is running anything it says
# about one is a guess or an accusation. Matching is on lower-cased text.
ROLE_WORDS: tuple[str, ...] = (
    "merlin",
    "percival",
    "morgana",
    "mordred",
    "oberon",
    "assassin",
    "minion",
    "loyal servant",
    "梅林",
    "派西维尔",
    "莫甘娜",
    "莫德雷德",
    "奥伯伦",
    "刺客",
    "爪牙",
    "忠臣",
)
ROLES_PUBLIC_AFTER = "game_finished"
"""The one public event after which roles are no longer secret."""


def names_a_role(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ROLE_WORDS)


# Rule explanations are fixed text chosen by key, so a model can pick which
# rule to mention but can never invent one.
_HINTS: dict[RuleHint, dict[Language, str]] = {
    "none": {"zh": "", "en": ""},
    "team_vote_majority": {
        "zh": "队伍需要严格过半的赞成票才能出发，平票视为否决。",
        "en": "A team needs a strict majority of approvals; a tie rejects it.",
    },
    "rejection_limit": {
        "zh": "同一轮任务连续五次组队被否决，邪恶方直接获胜。",
        "en": "Five rejected proposals in a row on one mission hand the game to evil.",
    },
    "double_fail_mission": {
        "zh": "七人及以上的对局，第四轮任务需要两张失败牌才算失败。",
        "en": "With seven or more players, the fourth mission needs two fail cards to fail.",
    },
    "mission_cards": {
        "zh": "好人只能出成功牌，邪恶方可以出成功或失败；只公布失败牌的数量。",
        "en": "Good must play success; evil may play either. Only the number of fails is shown.",
    },
    "assassination": {
        "zh": "好人完成三次任务后，刺客还有一次机会指认梅林；猜中则邪恶方获胜。",
        "en": "After three successful missions the Assassin names Merlin; if right, evil wins.",
    },
}

_REASONS: dict[str, dict[Language, str]] = {
    "missions_succeeded": {"zh": "三次任务成功", "en": "three missions succeeded"},
    "merlin_survived": {"zh": "刺客没有找到梅林", "en": "the Assassin missed Merlin"},
    "missions_failed": {"zh": "三次任务失败", "en": "three missions failed"},
    "proposals_rejected": {"zh": "连续五次组队被否决", "en": "five proposals were rejected"},
    "merlin_assassinated": {"zh": "梅林被刺杀", "en": "Merlin was assassinated"},
}

_SIDES: dict[str, dict[Language, str]] = {
    "good": {"zh": "正义方", "en": "Good"},
    "evil": {"zh": "邪恶方", "en": "Evil"},
}


def hint_text(hint: RuleHint, language: Language) -> str:
    return _HINTS[hint][language]


def _name(names: Mapping[str, str], player_id: object) -> str:
    return names.get(str(player_id), str(player_id))


def _names(names: Mapping[str, str], player_ids: object, language: Language) -> str:
    assert isinstance(player_ids, list)
    separator = "、" if language == "zh" else ", "
    return separator.join(_name(names, player_id) for player_id in player_ids)


def facts(entry: PublicEntry, names: Mapping[str, str], language: Language) -> str:
    """One sentence stating exactly what happened. No colour, no opinion."""
    data, zh = entry.data, language == "zh"
    match entry.kind:
        case "mission_started":
            leader = _name(names, data["leader"])
            if zh:
                return f"第 {data['mission']} 轮任务开始，{leader} 担任队长。"
            return f"Mission {data['mission']} begins. {leader} is the leader."
        case "team_proposed":
            leader, team = _name(names, data["leader"]), _names(names, data["team"], language)
            if zh:
                return f"{leader} 提议由 {team} 执行第 {data['mission']} 轮任务。"
            return f"{leader} proposes {team} for mission {data['mission']}."
        case "team_vote":
            approvals, rejections = data["approvals"], data["rejections"]
            assert isinstance(approvals, list) and isinstance(rejections, list)
            count = f"{len(approvals)}:{len(rejections)}"
            if zh:
                result = "队伍通过" if data["approved"] else "队伍被否决"
                return f"投票结果 {count}（赞成:反对），{result}。"
            result = "The team is approved" if data["approved"] else "The team is rejected"
            return f"The vote is {count} (approve:reject). {result}."
        case "mission_result":
            success = data["outcome"] == "success"
            if zh:
                result = "成功" if success else "失败"
                return f"第 {data['mission']} 轮任务{result}，出现 {data['fail_votes']} 张失败牌。"
            result = "succeeds" if success else "fails"
            return f"Mission {data['mission']} {result} with {data['fail_votes']} fail card(s)."
        case "assassination_started":
            assassin = _name(names, data["assassin"])
            if zh:
                return f"三次任务成功。刺客 {assassin} 现在指认梅林。"
            return f"Three missions have succeeded. {assassin}, the Assassin, now names Merlin."
        case "assassination":
            assassin, target = _name(names, data["assassin"]), _name(names, data["target"])
            if zh:
                return f"刺客 {assassin} 指认了 {target}。"
            return f"{assassin} names {target}."
        case "game_finished":
            side = _SIDES[str(data["winner"])][language]
            reason = _REASONS[str(data["reason"])][language]
            if zh:
                return f"对局结束：{side}获胜（{reason}）。"
            return f"The game is over: {side} wins ({reason})."
        case other:
            raise ValueError(f"No template for public event '{other}'.")


def default_tone(entry: PublicEntry) -> Tone:
    data = entry.data
    match entry.kind:
        case "team_vote":
            return "neutral" if data["approved"] else "tense"
        case "mission_result":
            return "triumphant" if data["outcome"] == "success" else "ominous"
        case "assassination_started" | "assassination":
            return "tense"
        case "game_finished":
            return "triumphant" if data["winner"] == "good" else "ominous"
        case _:
            return "neutral"


def default_hint(entry: PublicEntry) -> RuleHint:
    data = entry.data
    match entry.kind:
        case "team_proposed":
            return "team_vote_majority"
        case "team_vote":
            return "none" if data["approved"] else "rejection_limit"
        case "mission_result":
            return "mission_cards"
        case "assassination_started":
            return "assassination"
        case _:
            return "none"
