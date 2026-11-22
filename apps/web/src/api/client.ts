import { getApiBaseUrl } from "../config";

export type Phase =
  | "lobby"
  | "team_proposal"
  | "discussion"
  | "team_vote"
  | "mission_vote"
  | "assassination"
  | "finished";

export type Alignment = "good" | "evil";

export type Role =
  | "merlin"
  | "percival"
  | "loyal_servant"
  | "assassin"
  | "morgana"
  | "mordred"
  | "oberon"
  | "minion";

export type WinReason =
  | "missions_succeeded"
  | "merlin_survived"
  | "missions_failed"
  | "proposals_rejected"
  | "merlin_assassinated";

export interface Player {
  id: string;
  seat: number;
  name: string;
  is_bot: boolean;
  /** Who plays a bot seat: the built-in bot or a language model. */
  agent: "random" | "llm" | null;
  /** Which model plays an AI seat; null is the server's default. */
  driver: DriverId | null;
  /** The character in a bot seat. Null for a person. */
  persona: Persona | null;
  /** The game is waiting for this AI seat right now. */
  thinking: boolean;
  /** How this AI seat's latest turn was decided. */
  last_turn: "model" | "fallback" | null;
  fallback_reason: FallbackReason | null;
  is_you: boolean;
  is_host: boolean;
  is_leader: boolean;
  /** Only set for yourself, or for everyone once the game is over. */
  role: Role | null;
  alignment: Alignment | null;
  /** What your own role lets you know about this player. */
  seen_as: "evil" | "merlin_or_morgana" | null;
}

export type DriverId = "claude" | "deepseek" | "claude_code" | "codex";
/** Who plays one bot seat. */
export type SeatChoice = "bot" | DriverId;

export interface Persona {
  title: string;
  manner: string;
  color: string;
  /** Voice for read-aloud. */
  pitch: number;
  rate: number;
}

/** What an AI seat really thought when it acted. */
export interface Thought {
  /** Version of the game after the action it belongs to; a speech has the same one. */
  version: number;
  player_id: string;
  text: string;
}

export type FallbackReason =
  | "timeout"
  | "unavailable"
  | "refused"
  | "invalid_output"
  | "budget_exhausted";

export type AiStyle = "baseline" | "cautious" | "aggressive";
export type GmMode = "off" | "template" | "ai";

/** One thing the game master said about a public event. */
export interface Announcement {
  /** Version of the game after the event; unique and increasing. */
  version: number;
  tone: "neutral" | "tense" | "triumphant" | "ominous";
  /** What happened, stated by the server. Always present and always true. */
  facts: string;
  /** Equal to `facts` unless a model added colour. */
  announcement: string;
  rule_hint: string;
  source: "model" | "template";
}

export interface AiUsage {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
}

export interface RoomOptions {
  /** Who plays each bot seat, in seat order. */
  seats: SeatChoice[];
  /** Nobody sits down: you watch, and see every role. */
  spectate: boolean;
  aiStyle: AiStyle;
  gm: GmMode;
}

export interface DriverStatus {
  id: DriverId;
  label: string;
  available: boolean;
  /** Why it cannot be used right now, as a short code. */
  problem: string | null;
}

export interface SeatPersona {
  name: string;
  title: string;
  manner: string;
  color: string;
}

export interface ServerConfig {
  llm_available: boolean;
  gm_ai_available: boolean;
  drivers: DriverStatus[];
  /** Who sits in the bot seats, in seat order. */
  personas: SeatPersona[];
}

export interface Mission {
  number: number;
  team_size: number;
  fails_required: number;
  team: string[];
  outcome: "success" | "fail" | null;
  fail_votes: number | null;
}

export interface TeamVote {
  mission_number: number;
  proposal_number: number;
  team: string[];
  approvals: string[];
  rejections: string[];
  approved: boolean;
}

/** What one player said about the proposed team. Everyone at the table sees it. */
export interface Speech {
  player_id: string;
  /** Empty when the player passed. */
  text: string;
  /** Players the speaker openly said they do not trust. */
  suspects: string[];
}

/** One thing that happened in the open. `version` is the game's version after it. */
export type LogEntry =
  | { version: number; kind: "mission_started"; mission: number; leader: string }
  | {
      version: number;
      kind: "team_proposed";
      mission: number;
      proposal: number;
      leader: string;
      team: string[];
    }
  | {
      version: number;
      kind: "speech";
      mission: number;
      proposal: number;
      player: string;
      text: string;
      suspects: string[];
    }
  | {
      version: number;
      kind: "team_vote";
      mission: number;
      proposal: number;
      approved: boolean;
      approvals: string[];
      rejections: string[];
    }
  | {
      version: number;
      kind: "mission_result";
      mission: number;
      outcome: "success" | "fail";
      fail_votes: number;
    }
  | { version: number; kind: "assassination_started"; assassin: string }
  | { version: number; kind: "assassination"; assassin: string; target: string }
  | { version: number; kind: "game_finished"; winner: Alignment; reason: WinReason };

export type ActionType =
  | "start_game"
  | "propose_team"
  | "speak"
  | "vote_team"
  | "vote_mission"
  | "assassinate";

export interface LegalAction {
  type: ActionType;
  team_size: number | null;
  targets: string[];
  can_fail: boolean;
}

/** The game exactly as the server allows this seat to see it. */
export interface Game {
  game_id: string;
  room_code: string;
  gm: GmMode;
  announcements: Announcement[];
  /** The public record, oldest first. The table replays it step by step. */
  log: LogEntry[];
  /** You watch from outside the table: every role is shown and you have no seat. */
  spectator: boolean;
  /** What the AI seats really thought. Empty for a player until the game is over. */
  thoughts: Thought[];
  ai_usage: AiUsage;
  version: number;
  phase: Phase;
  you_id: string;
  leader_id: string | null;
  players: Player[];
  missions: Mission[];
  current_mission_number: number | null;
  proposal_number: number | null;
  max_rejected_proposals: number;
  missions_to_win: number;
  /** "official" for 5-10 players, "extended" for the 11-12 house rules. */
  ruleset_id: string;
  /** How many players are evil. Everyone at the table knows this. */
  evil_count: number;
  proposed_team: string[];
  /** Speeches about the latest proposal, in speaking order. */
  speeches: Speech[];
  /** Whose turn it is to speak, during the discussion. */
  speaker_id: string | null;
  team_voted: string[];
  your_team_vote: boolean | null;
  last_team_vote: TeamVote | null;
  mission_played: string[];
  your_mission_card: boolean | null;
  assassin_id: string | null;
  assassination_target_id: string | null;
  winner: Alignment | null;
  win_reason: WinReason | null;
  legal_actions: LegalAction[];
}

/** One model call within a turn: the answer, why the game turned it down, or the error. */
export interface Exchange {
  answer?: Record<string, unknown>;
  rejected?: string;
  error?: string;
  detail?: string;
}

/** One turn a model-driven seat played, with what it was shown and what it answered. */
export interface Turn {
  version: number;
  player_id: string;
  driver: string;
  source: "model" | "fallback";
  fallback_reason: string | null;
  attempts: number;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  observation: Record<string, unknown> | null;
  exchanges: Exchange[];
}

/** A finished game with everything behind it. */
export interface Replay {
  game: Game;
  turns: Turn[];
}

export interface RoomCreated {
  room_code: string;
  game_id: string;
  player_id: string;
  token: string;
  game: Game;
}

export type ActionRequest =
  | { type: "start_game" }
  | { type: "propose_team"; team: string[] }
  | { type: "speak"; text: string; suspects: string[] }
  | { type: "vote_team"; approve: boolean }
  | { type: "vote_mission"; success: boolean }
  | { type: "assassinate"; target_id: string };

/** What identifies this browser tab as a seat in a game. */
export interface Session {
  gameId: string;
  token: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, init);
  } catch {
    throw new ApiError(0, "network", "Could not reach the server.");
  }

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = body as { code?: unknown; message?: unknown } | null;
    throw new ApiError(
      response.status,
      typeof error?.code === "string" ? error.code : "http_error",
      typeof error?.message === "string" ? error.message : `HTTP ${response.status}`,
    );
  }
  return body as T;
}

function json(body: unknown, headers: Record<string, string> = {}): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  };
}

function authorization(session: Session): Record<string, string> {
  return { Authorization: `Bearer ${session.token}` };
}


export function createRoom(
  nickname: string,
  playerCount: number,
  options: RoomOptions,
): Promise<RoomCreated> {
  return request<RoomCreated>(
    "/rooms",
    json({
      nickname,
      player_count: playerCount,
      seats: options.seats,
      spectate: options.spectate,
      ai_style: options.aiStyle,
      gm: options.gm,
      language: "zh",
    }),
  );
}

export function getConfig(): Promise<ServerConfig> {
  return request<ServerConfig>("/config");
}

export function getGame(session: Session): Promise<Game> {
  return request<Game>(`/games/${session.gameId}`, { headers: authorization(session) });
}

/**
 * Submits one action. `expectedVersion` is the version the player was looking
 * at, so the server refuses the action if the game has moved on.
 */
export function submitAction(
  session: Session,
  expectedVersion: number,
  action: ActionRequest,
): Promise<Game> {
  return request<Game>(
    `/games/${session.gameId}/actions`,
    json({ ...action, expected_version: expectedVersion }, authorization(session)),
  );
}

/** Everything about a finished game, to replay it step by step. */
export function getReplay(session: Session): Promise<Replay> {
  return request<Replay>(`/games/${session.gameId}/replay`, { headers: authorization(session) });
}
