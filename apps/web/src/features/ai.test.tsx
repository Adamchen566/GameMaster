import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App, { HOST_POLLS, POLL_INTERVAL_MS } from "../App";
import type { Announcement, Game, Player } from "../api/client";
import { jsonResponse, legal, makeGame, makePlayers } from "../test/fixtures";
import { GamePage } from "./game/GamePage";
import { gameReducer } from "./game/gameReducer";
import type { AppState } from "./game/gameReducer";
import { LobbyPage } from "./lobby/LobbyPage";

function announcement(version: number, overrides: Partial<Announcement> = {}): Announcement {
  return {
    version,
    tone: "neutral",
    facts: `事实 ${version}`,
    announcement: `事实 ${version}`,
    rule_hint: "",
    source: "template",
    ...overrides,
  };
}

function withPlayer(id: string, changes: Partial<Player>): Player[] {
  return makePlayers().map((player) => (player.id === id ? { ...player, ...changes } : player));
}

function renderGame(game: Game) {
  render(
    <GamePage
      game={game}
      pending={false}
      error={null}
      selectedTeam={[]}
      onToggleTeam={vi.fn()}
      onAction={vi.fn()}
      onLeave={vi.fn()}
    />,
  );
}

describe("lobby: AI options", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function renderLobby(llmAvailable: boolean) {
    const onCreate = vi.fn();
    render(
      <LobbyPage creating={false} error={null} llmAvailable={llmAvailable} onCreate={onCreate} />,
    );
    fireEvent.change(screen.getByLabelText("昵称"), { target: { value: "Adam" } });
    return { onCreate, submit: () => fireEvent.click(screen.getByRole("button", { name: "创建对局" })) };
  }

  it("offers no AI seats and no AI host when the server has no model", () => {
    const { onCreate, submit } = renderLobby(false);

    expect(screen.queryByText(/AI 玩家席位/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("AI 主持")).not.toBeInTheDocument();
    expect(screen.getByText(/没有配置模型/)).toBeInTheDocument();
    expect(screen.getByLabelText("固定播报")).toBeChecked();

    fireEvent.click(screen.getByLabelText("关闭"));
    submit();

    expect(onCreate).toHaveBeenCalledWith("Adam", 5, { aiSeats: 0, aiStyle: "baseline", gm: "off" });
  });

  it("lets you pick AI seats, their style and an AI host", () => {
    const { onCreate, submit } = renderLobby(true);

    // The style only matters once there is an AI seat.
    expect(screen.queryByText("AI 玩家的打法")).not.toBeInTheDocument();
    expect(screen.getByText(/会产生费用/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("3 个"));
    fireEvent.click(screen.getByLabelText("谨慎"));
    fireEvent.click(screen.getByLabelText("AI 主持"));
    submit();

    expect(onCreate).toHaveBeenCalledWith("Adam", 5, { aiSeats: 3, aiStyle: "cautious", gm: "ai" });
  });

  it("never asks for more AI seats than there are bot seats", () => {
    const { onCreate, submit } = renderLobby(true);

    fireEvent.click(screen.getByLabelText("10 人"));
    fireEvent.click(screen.getByLabelText("9 个"));
    fireEvent.click(screen.getByLabelText("5 人"));

    expect(screen.queryByLabelText("9 个")).not.toBeInTheDocument();
    expect(screen.getByLabelText("4 个")).toBeChecked();
    submit();

    expect(onCreate).toHaveBeenCalledWith("Adam", 5, { aiSeats: 4, aiStyle: "baseline", gm: "template" });
  });
});

describe("game: AI seats and the host", () => {
  it("marks model seats, random bots, and who the game is waiting for", () => {
    const players = withPlayer("p2", { agent: "llm", thinking: true });
    renderGame(makeGame({ players, legal_actions: [] }));

    const rows = screen.getAllByRole("listitem");
    const gawain = rows.find((row) => within(row).queryByText("Gawain") !== null);
    const lancelot = rows.find((row) => within(row).queryByText("Lancelot") !== null);
    expect(gawain).toBeDefined();
    expect(lancelot).toBeDefined();

    expect(within(gawain as HTMLElement).getByText("AI")).toBeInTheDocument();
    expect(within(gawain as HTMLElement).getByText("思考中…")).toBeInTheDocument();
    expect(within(gawain as HTMLElement).queryByText("机器人")).not.toBeInTheDocument();
    expect(within(lancelot as HTMLElement).getByText("机器人")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("等待 Gawain 行动…");
  });

  it("says so when a model seat's last move was played by the bot, and why", () => {
    const players = withPlayer("p3", {
      agent: "llm",
      last_turn: "fallback",
      fallback_reason: "timeout",
    });
    renderGame(makeGame({ players }));

    expect(screen.getByText("上一步由机器人代打：模型超时")).toBeInTheDocument();
  });

  it("does not flag a model seat that played its own move", () => {
    renderGame(makeGame({ players: withPlayer("p3", { agent: "llm", last_turn: "model" }) }));

    expect(screen.queryByText(/代打/)).not.toBeInTheDocument();
  });

  it("shows the host's latest announcements, newest first", () => {
    const announcements = [1, 2, 3, 4, 5, 6, 7].map((version) => announcement(version));
    renderGame(makeGame({ announcements }));

    const host = screen.getByRole("region", { name: "主持人" });
    const lines = within(host).getAllByRole("listitem");

    expect(lines.map((line) => line.textContent)).toEqual([
      "事实 7",
      "事实 6",
      "事实 5",
      "事实 4",
      "事实 3",
    ]);
  });

  it("always shows the fact next to a line a model wrote", () => {
    const announcements = [
      announcement(4, {
        source: "model",
        tone: "ominous",
        announcement: "火把忽明忽暗。",
        facts: "第 1 轮任务失败，出现 1 张失败牌。",
        rule_hint: "好人只能出成功牌。",
      }),
    ];
    renderGame(makeGame({ announcements }));

    const host = screen.getByRole("region", { name: "主持人" });
    expect(within(host).getByText("火把忽明忽暗。")).toBeInTheDocument();
    expect(within(host).getByText("第 1 轮任务失败，出现 1 张失败牌。")).toBeInTheDocument();
    expect(within(host).getByText("规则提示：好人只能出成功牌。")).toBeInTheDocument();
  });

  it("has no host section when the host is off", () => {
    renderGame(makeGame({ gm: "off", announcements: [] }));

    expect(screen.queryByRole("region", { name: "主持人" })).not.toBeInTheDocument();
  });
});

describe("reducer: background refresh", () => {
  const session = { gameId: "g1", token: "tok" };
  const inGame = (game: Game, extra: Partial<AppState> = {}): AppState =>
    ({ screen: "game", session, game, pending: false, error: null, selectedTeam: [], ...extra }) as AppState;

  it("takes a newer game without touching a request in flight or an error", () => {
    const state = inGame(makeGame({ version: 8 }), { pending: true, error: "稍等" } as Partial<AppState>);
    const newer = makeGame({ version: 9 });

    expect(gameReducer(state, { type: "game_polled", game: newer })).toEqual({
      ...state,
      game: newer,
    });
  });

  it("never moves the game backwards", () => {
    const state = inGame(makeGame({ version: 9 }));

    expect(gameReducer(state, { type: "game_polled", game: makeGame({ version: 8 }) })).toBe(state);
  });

  it("keeps a half-picked team only while the position is the same", () => {
    const state = inGame(makeGame({ version: 8 }), { selectedTeam: ["p1"] } as Partial<AppState>);

    const same = gameReducer(state, { type: "game_polled", game: makeGame({ version: 8 }) });
    const moved = gameReducer(state, { type: "game_polled", game: makeGame({ version: 9 }) });

    expect(same).toMatchObject({ selectedTeam: ["p1"] });
    expect(moved).toMatchObject({ selectedTeam: [] });
  });

  it("is ignored outside a game", () => {
    const lobby: AppState = { screen: "lobby", creating: false, error: null };

    expect(gameReducer(lobby, { type: "game_polled", game: makeGame() })).toBe(lobby);
  });
});

describe("app: waiting for AI seats", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.sessionStorage.setItem("avalon.session", JSON.stringify({ gameId: "g1", token: "tok" }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    window.sessionStorage.clear();
  });

  function serveGames(games: Game[]) {
    let reads = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/games/g1") {
        const game = games[Math.min(reads, games.length - 1)];
        reads += 1;
        return jsonResponse(game);
      }
      return jsonResponse({ llm_available: true, status: "ok" });
    });
    vi.stubGlobal("fetch", fetchMock);
    return { reads: () => reads };
  }

  const thinking = makeGame({
    version: 8,
    legal_actions: [],
    players: withPlayer("p2", { agent: "llm", thinking: true }),
  });
  const yourTurn = makeGame({ version: 12, legal_actions: [legal("vote_team")] });

  it("polls while a model seat is thinking and stops when it is your turn", async () => {
    const server = serveGames([thinking, thinking, yourTurn]);
    render(<App />);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByRole("status")).toHaveTextContent("等待 Gawain 行动…");
    expect(server.reads()).toBe(1);

    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    expect(server.reads()).toBe(2);
    expect(screen.getByRole("status")).toHaveTextContent("等待 Gawain 行动…");

    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    expect(server.reads()).toBe(3);
    expect(screen.getByRole("button", { name: "赞成" })).toBeEnabled();

    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5));
    expect(server.reads()).toBe(3);
  });

  it("looks a few times for the AI host's line, then settles for the template", async () => {
    const template = { version: 2, tone: "neutral", facts: "事实", announcement: "事实", rule_hint: "", source: "template" } as const;
    const waitingForHost = makeGame({ gm: "ai", announcements: [template] });
    const server = serveGames([waitingForHost]);
    render(<App />);
    await act(() => vi.advanceTimersByTimeAsync(0));

    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 20));

    expect(server.reads()).toBe(1 + HOST_POLLS);
  });

  it("stops looking as soon as the AI host's line arrives", async () => {
    const template = { version: 2, tone: "neutral", facts: "事实", announcement: "事实", rule_hint: "", source: "template" } as const;
    const written = { ...template, announcement: "火把忽明忽暗。", source: "model" } as const;
    const server = serveGames([
      makeGame({ gm: "ai", announcements: [template] }),
      makeGame({ gm: "ai", announcements: [written] }),
    ]);
    render(<App />);
    await act(() => vi.advanceTimersByTimeAsync(0));

    // One interval per act, so React re-renders between polls as it does in a browser.
    for (let tick = 0; tick < 10; tick += 1) {
      await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
    }

    expect(server.reads()).toBe(2);
    expect(screen.getByText("火把忽明忽暗。")).toBeInTheDocument();
  });

  it("does not poll when nobody is thinking", async () => {
    const server = serveGames([yourTurn]);
    render(<App />);
    await act(() => vi.advanceTimersByTimeAsync(0));

    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5));

    expect(server.reads()).toBe(1);
  });
});
