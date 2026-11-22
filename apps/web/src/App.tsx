import { useEffect, useReducer, useRef, useState } from "react";

import { ApiError, createRoom, getConfig, getGame, submitAction } from "./api/client";
import type { ActionRequest, RoomOptions, ServerConfig } from "./api/client";
import { GamePage } from "./features/game/GamePage";
import { gameReducer, initialState } from "./features/game/gameReducer";
import { describeError } from "./features/game/labels";
import { LobbyPage, NO_MODELS } from "./features/lobby/LobbyPage";
import { clearSession, loadSession, saveSession } from "./session";
import "./styles.css";

export const POLL_INTERVAL_MS = 1500;
/** How many times to look for the AI host's line before settling for the template. */
export const HOST_POLLS = 4;

export default function App() {
  const [state, dispatch] = useReducer(gameReducer, undefined, () => initialState(loadSession()));
  // Guards against a second click landing before the first re-render.
  const busy = useRef(false);
  const [config, setConfig] = useState<ServerConfig>(NO_MODELS);

  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then((loaded) => {
        if (!cancelled) {
          // An older server answers with less; keep what always works for the rest.
          setConfig({ ...NO_MODELS, ...loaded });
        }
      })
      .catch(() => {
        // Unknown means "offer only what always works".
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // While the game waits for an AI seat, ask the server now and then: model
  // turns are played in the background and arrive without any action of ours.
  // The AI host also writes in the background; give its line a few polls to arrive.
  const game = state.screen === "game" ? state.game : null;
  const waitingForSeat = game !== null && game.players.some((player) => player.thinking);
  const waitingForHost =
    game !== null && game.gm === "ai" && game.announcements.at(-1)?.source === "template";
  const waitingSession =
    state.screen === "game" && (waitingForSeat || waitingForHost) ? state.session : null;
  const waitingVersion = game?.version ?? null;
  useEffect(() => {
    if (waitingSession === null) {
      return;
    }
    let cancelled = false;
    let polls = 0;
    const timer = window.setInterval(() => {
      if (busy.current) {
        return;
      }
      polls += 1;
      if (!waitingForSeat && polls > HOST_POLLS) {
        // The host's line did not come (slow or failing model): the template stays.
        window.clearInterval(timer);
        return;
      }
      getGame(waitingSession)
        .then((game) => {
          if (!cancelled) {
            dispatch({ type: "game_polled", game });
          }
        })
        .catch(() => {
          // A missed poll is harmless; the next one will try again.
        });
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [waitingSession, waitingVersion, waitingForSeat]);

  const resumingSession = state.screen === "resuming" ? state.session : null;
  useEffect(() => {
    if (resumingSession === null) {
      return;
    }
    let cancelled = false;

    getGame(resumingSession)
      .then((game) => {
        if (!cancelled) {
          dispatch({ type: "game_loaded", game });
        }
      })
      .catch(() => {
        if (!cancelled) {
          clearSession();
          dispatch({ type: "session_lost" });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [resumingSession]);

  async function handleCreate(nickname: string, playerCount: number, options: RoomOptions) {
    if (busy.current) {
      return;
    }
    busy.current = true;
    dispatch({ type: "create_started" });
    try {
      const room = await createRoom(nickname, playerCount, options);
      const session = { gameId: room.game_id, token: room.token };
      saveSession(session);
      dispatch({ type: "room_created", session, game: room.game });
    } catch (error) {
      dispatch({ type: "create_failed", message: describeError(error) });
    } finally {
      busy.current = false;
    }
  }

  async function handleAction(action: ActionRequest) {
    if (state.screen !== "game" || busy.current) {
      return;
    }
    busy.current = true;
    dispatch({ type: "action_started" });
    try {
      const game = await submitAction(state.session, state.game.version, action);
      dispatch({ type: "game_loaded", game });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        // The game moved on without us: show the current position, then the reason.
        const game = await getGame(state.session).catch(() => null);
        if (game !== null) {
          dispatch({ type: "game_loaded", game });
        }
      }
      dispatch({ type: "action_failed", message: describeError(error) });
    } finally {
      busy.current = false;
    }
  }

  function handleLeave() {
    clearSession();
    dispatch({ type: "left_game" });
  }

  switch (state.screen) {
    case "lobby":
      return (
        <LobbyPage
          creating={state.creating}
          error={state.error}
          config={config}
          onCreate={handleCreate}
        />
      );
    case "resuming":
      return (
        <main className="page page--narrow">
          <p role="status">正在回到对局…</p>
        </main>
      );
    case "game":
      return (
        <GamePage
          game={state.game}
          pending={state.pending}
          error={state.error}
          selectedTeam={state.selectedTeam}
          onToggleTeam={(playerId) => dispatch({ type: "team_toggled", playerId })}
          onAction={handleAction}
          onLeave={handleLeave}
        />
      );
  }
}
