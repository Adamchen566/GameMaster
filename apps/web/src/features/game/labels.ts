import { ApiError } from "../../api/client";
import type { Alignment, Phase, Player, Role, WinReason } from "../../api/client";

export const ROLE_NAMES: Record<Role, string> = {
  merlin: "梅林",
  percival: "派西维尔",
  loyal_servant: "亚瑟的忠臣",
  assassin: "刺客",
  morgana: "莫甘娜",
  mordred: "莫德雷德",
  oberon: "奥伯伦",
  minion: "莫德雷德的爪牙",
};

export const ROLE_HINTS: Record<Role, string> = {
  merlin: "你知道谁是邪恶方。别暴露自己，否则会被刺杀。",
  percival: "你知道哪两个人是梅林和莫甘娜，但分不清谁是谁。",
  loyal_servant: "你没有额外信息。靠投票和任务结果找出邪恶方。",
  assassin: "你认识同伴。若正义方赢下三次任务，由你指认梅林。",
  morgana: "你认识同伴。在派西维尔眼里，你看起来像梅林。",
  mordred: "你认识同伴。梅林看不见你。",
  oberon: "你是邪恶方，但你不认识同伴，同伴也不认识你。",
  minion: "你认识同伴。让任务失败，或帮刺客找出梅林。",
};

export const ALIGNMENT_NAMES: Record<Alignment, string> = {
  good: "正义方",
  evil: "邪恶方",
};

export const PHASE_NAMES: Record<Phase, string> = {
  lobby: "等待开始",
  team_proposal: "队长组队",
  team_vote: "组队投票",
  mission_vote: "执行任务",
  assassination: "刺杀梅林",
  finished: "对局结束",
};

export const WIN_REASONS: Record<WinReason, string> = {
  missions_succeeded: "三次任务成功",
  merlin_survived: "三次任务成功，刺客没有找到梅林",
  missions_failed: "三次任务失败",
  proposals_rejected: "连续五次组队被否决",
  merlin_assassinated: "梅林被刺客找到了",
};

export const SEEN_AS_NAMES: Record<NonNullable<Player["seen_as"]>, string> = {
  evil: "邪恶方",
  merlin_or_morgana: "梅林或莫甘娜",
};

const ERROR_MESSAGES: Record<string, string> = {
  network: "连不上服务器，请确认后端已启动后重试。",
  invalid_player_count: "这个人数不支持，请选择 5 到 10 人。",
  missing_token: "登录信息丢失，请重新创建对局。",
  invalid_token: "登录信息已失效，请重新创建对局。",
  wrong_game: "这个令牌不属于这局游戏。",
  game_not_found: "这局游戏已经不存在了（服务器可能重启过）。",
  wrong_phase: "现在不能做这个操作，画面已刷新。",
  stale_version: "局面已经变化，画面已刷新，请重新操作。",
  already_voted: "你已经投过票了。",
  not_leader: "只有队长可以组队。",
  not_on_team: "只有任务成员可以出牌。",
  not_assassin: "只有刺客可以指认。",
  wrong_team_size: "队伍人数不对。",
  duplicate_team_member: "同一个人不能选两次。",
  unknown_team_member: "选中的人不在这局里。",
  good_must_succeed: "正义方只能出成功牌。",
  invalid_target: "必须指认另一名玩家。",
};

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return ERROR_MESSAGES[error.code] ?? `操作失败：${error.message}`;
  }
  return "出了点问题，请重试。";
}
