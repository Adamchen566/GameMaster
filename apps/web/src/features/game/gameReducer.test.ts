import { describe, expect, it } from "vitest";

import { legal, makeGame } from "../../test/fixtures";
import { gameReducer, initialState } from "./gameReducer";
import type { AppState } from "./gameReducer";

const SESSION = { gameId: "g1", token: "secret" };

function inGame(overrides: Partial<Extract<AppState, { screen: "game" }>> = {}): AppState {
  return {
    screen: "game",
    session: SESSION,
    game: makeGame(),
    pending: false,
    error: null,
    selectedTeam: [],
    ...overrides,
  };
}

function asLeader(selectedTeam: string[] = []): AppState {
  const game = makeGame({
    phase: "team_proposal",
    proposed_team: [],
    team_voted: [],
    legal_actions: [legal("propose_team", { team_size: 2, targets: ["p1", "p2", "p3"] })],
  });
  return inGame({ game, selectedTeam });
}

describe("gameReducer", () => {
  it("starts in the lobby without a session and resumes with one", () => {
    expect(initialState(null)).toEqual({ screen: "lobby", creating: false, error: null });
    expect(initialState(SESSION)).toEqual({ screen: "resuming", session: SESSION });
  });

  it("tracks room creation and keeps the error when it fails", () => {
    const creating = gameReducer(initialState(null), { type: "create_started" });
    expect(creating).toMatchObject({ creating: true, error: null });

    const failed = gameReducer(creating, { type: "create_failed", message: "连不上" });
    expect(failed).toEqual({ screen: "lobby", creating: false, error: "连不上" });
  });

  it("enters the game when a room is created or a session is resumed", () => {
    const game = makeGame();

    const created = gameReducer(initialState(null), { type: "room_created", session: SESSION, game });
    const resumed = gameReducer(initialState(SESSION), { type: "game_loaded", game });

    expect(created).toEqual(inGame({ game }));
    expect(resumed).toEqual(inGame({ game }));
  });

  it("marks an action as pending and clears it when the new game arrives", () => {
    const pending = gameReducer(inGame({ error: "旧错误" }), { type: "action_started" });
    expect(pending).toMatchObject({ pending: true, error: null });

    const next = makeGame({ version: 9, phase: "mission_vote" });
    expect(gameReducer(pending, { type: "game_loaded", game: next })).toMatchObject({
      game: next,
      pending: false,
      error: null,
    });
  });

  it("keeps the game and shows the error when an action fails", () => {
    const state = gameReducer(inGame({ pending: true }), {
      type: "action_failed",
      message: "现在不能做这个操作",
    });

    expect(state).toMatchObject({ pending: false, error: "现在不能做这个操作" });
    expect(state).toHaveProperty("game.version", 8);
  });

  it("adds and removes team members", () => {
    let state = gameReducer(asLeader(), { type: "team_toggled", playerId: "p1" });
    state = gameReducer(state, { type: "team_toggled", playerId: "p3" });
    expect(state).toHaveProperty("selectedTeam", ["p1", "p3"]);

    state = gameReducer(state, { type: "team_toggled", playerId: "p1" });
    expect(state).toHaveProperty("selectedTeam", ["p3"]);
  });

  it("never selects more players than the mission needs", () => {
    const state = gameReducer(asLeader(["p1", "p2"]), { type: "team_toggled", playerId: "p3" });

    expect(state).toHaveProperty("selectedTeam", ["p1", "p2"]);
  });

  it("ignores players the server did not offer and picks when you are not the leader", () => {
    expect(gameReducer(asLeader(), { type: "team_toggled", playerId: "ghost" })).toHaveProperty(
      "selectedTeam",
      [],
    );
    expect(gameReducer(inGame(), { type: "team_toggled", playerId: "p1" })).toHaveProperty(
      "selectedTeam",
      [],
    );
  });

  it("drops a half-picked team once the position changes, but not on a refresh", () => {
    const picked = asLeader(["p1"]);
    if (picked.screen !== "game") {
      throw new Error("expected a game");
    }

    const refreshed = gameReducer(picked, { type: "game_loaded", game: picked.game });
    const moved = gameReducer(picked, {
      type: "game_loaded",
      game: { ...picked.game, version: picked.game.version + 3 },
    });

    expect(refreshed).toHaveProperty("selectedTeam", ["p1"]);
    expect(moved).toHaveProperty("selectedTeam", []);
  });

  it("returns to the lobby when leaving or when the session is gone", () => {
    const lobby = { screen: "lobby", creating: false, error: null };

    expect(gameReducer(inGame(), { type: "left_game" })).toEqual(lobby);
    expect(gameReducer(initialState(SESSION), { type: "session_lost" })).toEqual(lobby);
  });

  it("ignores events that do not belong to the current screen", () => {
    const lobby = initialState(null);
    const game = inGame();

    expect(gameReducer(lobby, { type: "action_started" })).toBe(lobby);
    expect(gameReducer(lobby, { type: "action_failed", message: "x" })).toBe(lobby);
    expect(gameReducer(lobby, { type: "team_toggled", playerId: "p1" })).toBe(lobby);
    expect(gameReducer(lobby, { type: "game_loaded", game: makeGame() })).toBe(lobby);
    expect(gameReducer(game, { type: "create_started" })).toBe(game);
    expect(gameReducer(game, { type: "create_failed", message: "x" })).toBe(game);
  });
});
