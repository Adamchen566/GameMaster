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
  /** Who plays a bot seat: the random bot or a language model. */
  agent: "random" | "llm" | null;
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
  aiSeats: number;
  aiStyle: AiStyle;
  gm: GmMode;
}

export interface ServerConfig {
  llm_available: boolean;
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

const DEFAULT_ROOM_OPTIONS: RoomOptions = { aiSeats: 0, aiStyle: "baseline", gm: "template" };

export function createRoom(
  nickname: string,
  playerCount: number,
  options: RoomOptions = DEFAULT_ROOM_OPTIONS,
): Promise<RoomCreated> {
  return request<RoomCreated>(
    "/rooms",
    json({
      nickname,
      player_count: playerCount,
      ai_seats: options.aiSeats,
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
