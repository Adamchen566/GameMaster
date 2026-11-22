import { useEffect, useReducer, useRef } from "react";

import { ApiError, createRoom, getGame, submitAction } from "./api/client";
import type { ActionRequest } from "./api/client";
import { GamePage } from "./features/game/GamePage";
import { gameReducer, initialState } from "./features/game/gameReducer";
import { describeError } from "./features/game/labels";
import { LobbyPage } from "./features/lobby/LobbyPage";
import { clearSession, loadSession, saveSession } from "./session";
import "./styles.css";

export default function App() {
  const [state, dispatch] = useReducer(gameReducer, undefined, () => initialState(loadSession()));
  // Guards against a second click landing before the first re-render.
  const busy = useRef(false);

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

  async function handleCreate(nickname: string, playerCount: number) {
    if (busy.current) {
      return;
    }
    busy.current = true;
    dispatch({ type: "create_started" });
    try {
      const room = await createRoom(nickname, playerCount);
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
      return <LobbyPage creating={state.creating} error={state.error} onCreate={handleCreate} />;
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
