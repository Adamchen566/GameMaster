import { getApiBaseUrl } from "../config";

export type Phase =
  | "lobby"
  | "team_proposal"
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
  is_you: boolean;
  is_host: boolean;
  is_leader: boolean;
  /** Only set for yourself, or for everyone once the game is over. */
  role: Role | null;
  alignment: Alignment | null;
  /** What your own role lets you know about this player. */
  seen_as: "evil" | "merlin_or_morgana" | null;
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

export type ActionType =
  | "start_game"
  | "propose_team"
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

export function createRoom(nickname: string, playerCount: number): Promise<RoomCreated> {
  return request<RoomCreated>("/rooms", json({ nickname, player_count: playerCount }));
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
