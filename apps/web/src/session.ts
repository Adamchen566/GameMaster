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
