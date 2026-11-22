import type { Game, Session } from "../../api/client";

/**
 * All UI state lives here. The server's view of the game is held once, in
 * `game`; the only client-side additions are what the player is in the middle
 * of doing (a half-picked team, a request in flight, the last error).
 */
export type AppState =
  | { screen: "lobby"; creating: boolean; error: string | null }
  | { screen: "resuming"; session: Session }
  | {
      screen: "game";
      session: Session;
      game: Game;
      pending: boolean;
      error: string | null;
      selectedTeam: string[];
    };

export type AppAction =
  | { type: "create_started" }
  | { type: "create_failed"; message: string }
  | { type: "room_created"; session: Session; game: Game }
  | { type: "game_loaded"; game: Game }
  | { type: "game_polled"; game: Game }
  | { type: "session_lost" }
  | { type: "action_started" }
  | { type: "action_failed"; message: string }
  | { type: "team_toggled"; playerId: string }
  | { type: "left_game" };

const LOBBY: AppState = { screen: "lobby", creating: false, error: null };

export function initialState(session: Session | null): AppState {
  return session === null ? LOBBY : { screen: "resuming", session };
}

export function gameReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "create_started":
      return state.screen === "lobby" ? { ...state, creating: true, error: null } : state;

    case "create_failed":
      return state.screen === "lobby"
        ? { ...state, creating: false, error: action.message }
        : state;

    case "room_created":
      return inGame(action.session, action.game);

    case "game_loaded":
      if (state.screen === "resuming") {
        return inGame(state.session, action.game);
      }
      if (state.screen === "game") {
        // A half-picked team only makes sense for the position it was picked in.
        const samePosition = action.game.version === state.game.version;
        return {
          ...state,
          game: action.game,
          pending: false,
          error: null,
          selectedTeam: samePosition ? state.selectedTeam : [],
        };
      }
      return state;

    case "game_polled":
      // A background refresh while AI seats play. It must not disturb a request
      // in flight or an error on screen, and it never moves the game backwards.
      if (state.screen !== "game" || action.game.version < state.game.version) {
        return state;
      }
      return {
        ...state,
        game: action.game,
        selectedTeam: action.game.version === state.game.version ? state.selectedTeam : [],
      };

    case "action_started":
      return state.screen === "game" ? { ...state, pending: true, error: null } : state;

    case "action_failed":
      return state.screen === "game"
        ? { ...state, pending: false, error: action.message }
        : state;

    case "team_toggled":
      return state.screen === "game"
        ? { ...state, selectedTeam: toggleTeamMember(state, action.playerId) }
        : state;

    case "session_lost":
    case "left_game":
      return LOBBY;
  }
}

function inGame(session: Session, game: Game): AppState {
  return { screen: "game", session, game, pending: false, error: null, selectedTeam: [] };
}

function toggleTeamMember(
  state: Extract<AppState, { screen: "game" }>,
  playerId: string,
): string[] {
  const proposal = state.game.legal_actions.find((legal) => legal.type === "propose_team");
  if (proposal === undefined || !proposal.targets.includes(playerId)) {
    return state.selectedTeam;
  }
  if (state.selectedTeam.includes(playerId)) {
    return state.selectedTeam.filter((id) => id !== playerId);
  }
  if (state.selectedTeam.length >= (proposal.team_size ?? 0)) {
    return state.selectedTeam;
  }
  return [...state.selectedTeam, playerId];
}
