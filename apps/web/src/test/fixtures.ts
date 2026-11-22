import type { Game, LegalAction, Player } from "../api/client";

const NAMES = ["Adam", "Gawain", "Lancelot", "Tristan", "Galahad"];

/** Five seats as a loyal servant would see them mid-game: only their own role is known. */
export function makePlayers(): Player[] {
  return NAMES.map((name, seat) => ({
    id: `p${seat + 1}`,
    seat,
    name,
    is_bot: seat !== 0,
    agent: seat === 0 ? null : "random",
    thinking: false,
    last_turn: null,
    fallback_reason: null,
    is_you: seat === 0,
    is_host: seat === 0,
    is_leader: seat === 1,
    role: seat === 0 ? "loyal_servant" : null,
    alignment: seat === 0 ? "good" : null,
    seen_as: null,
  }));
}

export function legal(type: LegalAction["type"], extra: Partial<LegalAction> = {}): LegalAction {
  return { type, team_size: null, targets: [], can_fail: false, ...extra };
}

/** A running game waiting for you to vote on a proposed team. */
export function makeGame(overrides: Partial<Game> = {}): Game {
  return {
    game_id: "g1",
    room_code: "ABC234",
    gm: "template",
    announcements: [],
    ai_usage: { calls: 0, input_tokens: 0, output_tokens: 0, cost_usd: null },
    version: 8,
    phase: "team_vote",
    you_id: "p1",
    leader_id: "p2",
    players: makePlayers(),
    missions: [2, 3, 2, 3, 3].map((team_size, index) => ({
      number: index + 1,
      team_size,
      fails_required: 1,
      team: [],
      outcome: null,
      fail_votes: null,
    })),
    current_mission_number: 1,
    proposal_number: 1,
    max_rejected_proposals: 5,
    missions_to_win: 3,
    proposed_team: ["p2", "p3"],
    speeches: [],
    speaker_id: null,
    team_voted: ["p2", "p3", "p4", "p5"],
    your_team_vote: null,
    last_team_vote: null,
    mission_played: [],
    your_mission_card: null,
    assassin_id: null,
    assassination_target_id: null,
    winner: null,
    win_reason: null,
    legal_actions: [legal("vote_team")],
    ...overrides,
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}
