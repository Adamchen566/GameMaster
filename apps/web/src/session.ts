import type { Session } from "./api/client";

const KEY = "avalon.session";

/**
 * The reconnect token lives in sessionStorage: it survives a reload of this
 * tab, but is not shared with other tabs and is gone when the tab closes.
 */
export function loadSession(): Session | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (raw === null) {
      return null;
    }
    const value: unknown = JSON.parse(raw);
    if (
      typeof value === "object" &&
      value !== null &&
      typeof (value as Session).gameId === "string" &&
      typeof (value as Session).token === "string"
    ) {
      return { gameId: (value as Session).gameId, token: (value as Session).token };
    }
  } catch {
    // Unreadable or blocked storage is the same as having no session.
  }
  return null;
}

export function saveSession(session: Session): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // The game still works for this page load; it just cannot be resumed.
  }
}

export function clearSession(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to clear.
  }
}

const HISTORY_KEY = "avalon.history";
/** Enough to find a game again; older ones drop off. */
const HISTORY_LIMIT = 20;

/** A game played in this browser, kept so it can be replayed later. */
export interface PastGame extends Session {
  createdAt: string;
  playerCount: number;
  nickname: string;
  spectate: boolean;
}

function isPastGame(value: unknown): value is PastGame {
  const game = value as PastGame;
  return (
    typeof value === "object" &&
    value !== null &&
    typeof game.gameId === "string" &&
    typeof game.token === "string" &&
    typeof game.createdAt === "string" &&
    typeof game.playerCount === "number" &&
    typeof game.nickname === "string" &&
    typeof game.spectate === "boolean"
  );
}

/**
 * Games played here, newest first. Unlike the live session this lives in
 * localStorage, so a game can be replayed after the tab is closed. The token
 * it keeps can read the game and, while it is still on, play its seat.
 */
export function loadHistory(): PastGame[] {
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    const value: unknown = raw === null ? [] : JSON.parse(raw);
    return Array.isArray(value) ? value.filter(isPastGame) : [];
  } catch {
    return [];
  }
}

export function rememberGame(game: PastGame): PastGame[] {
  const history = [game, ...loadHistory().filter((old) => old.gameId !== game.gameId)].slice(
    0,
    HISTORY_LIMIT,
  );
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  } catch {
    // Without storage the game can still be played, just not found again later.
  }
  return history;
}
