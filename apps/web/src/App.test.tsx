import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { Game } from "./api/client";
import { jsonResponse, legal, makeGame } from "./test/fixtures";

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;

/** Routes fetch calls by "METHOD path"; unknown calls fail the test loudly. */
function serve(routes: Record<string, Handler>) {
  const calls: { key: string; init: RequestInit | undefined }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    calls.push({ key, init });
    const handler = routes[key];
    if (handler === undefined) {
      throw new Error(`unexpected request: ${key}`);
    }
    return handler(init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    count: (key: string) => calls.filter((call) => call.key === key).length,
    body: (key: string) => JSON.parse(String(calls.find((call) => call.key === key)?.init?.body)),
  };
}

const HEALTH: Record<string, Handler> = {
  "GET /api/health": () => jsonResponse({ status: "ok" }),
};

function room(game: Game) {
  return { room_code: game.room_code, game_id: game.game_id, player_id: "p1", token: "tok", game };
}

function fillAndSubmit(nickname = "Adam") {
  fireEvent.change(screen.getByLabelText("昵称"), { target: { value: nickname } });
  fireEvent.click(screen.getByRole("button", { name: "创建对局" }));
}

function rememberSession() {
  window.sessionStorage.setItem("avalon.session", JSON.stringify({ gameId: "g1", token: "tok" }));
}

describe("App", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("opens on the lobby and reports that the service is online", async () => {
    serve(HEALTH);

    render(<App />);

    expect(screen.getByRole("heading", { name: "阿瓦隆 · 单人对局" })).toBeInTheDocument();
    expect(screen.getByText("正在连接服务…")).toBeInTheDocument();
    expect(await screen.findByText("服务在线")).toBeInTheDocument();
  });

  it("says so when the service cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));

    render(<App />);

    expect(await screen.findByText(/无法连接服务/)).toBeInTheDocument();
  });

  it("requests the API base URL configured in the environment", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/");
    const fetchMock = vi.fn(() => new Promise(() => undefined));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(fetchMock).toHaveBeenCalledWith("https://api.example.test/health");
  });

  it("creates a room, remembers the session and shows the game", async () => {
    const lobbyGame = makeGame({
      phase: "lobby",
      version: 0,
      missions: [],
      proposed_team: [],
      team_voted: [],
      legal_actions: [legal("start_game")],
    });
    const server = serve({ ...HEALTH, "POST /api/rooms": () => jsonResponse(room(lobbyGame), 201) });

    render(<App />);
    fillAndSubmit();

    expect(await screen.findByRole("button", { name: "开始游戏" })).toBeInTheDocument();
    expect(server.body("POST /api/rooms")).toEqual({ nickname: "Adam", player_count: 5 });
    expect(JSON.parse(window.sessionStorage.getItem("avalon.session") ?? "null")).toEqual({
      gameId: "g1",
      token: "tok",
    });
  });

  it("keeps the form and explains when the room cannot be created", async () => {
    serve({
      ...HEALTH,
      "POST /api/rooms": () =>
        jsonResponse({ code: "invalid_player_count", message: "nope" }, 422),
    });

    render(<App />);
    fillAndSubmit("Adam");

    expect(await screen.findByRole("alert")).toHaveTextContent("这个人数不支持");
    expect(screen.getByLabelText("昵称")).toHaveValue("Adam");
    expect(screen.getByRole("button", { name: "创建对局" })).toBeEnabled();
    expect(window.sessionStorage.getItem("avalon.session")).toBeNull();
  });

  it("sends only one request when the create button is clicked twice", async () => {
    let finish: (response: Response) => void = () => undefined;
    const server = serve({
      ...HEALTH,
      "POST /api/rooms": () => new Promise<Response>((resolve) => (finish = resolve)),
    });

    render(<App />);
    fillAndSubmit();
    fireEvent.submit(screen.getByLabelText("昵称").closest("form") as HTMLFormElement);

    expect(await screen.findByRole("button", { name: "正在创建…" })).toBeDisabled();
    expect(server.count("POST /api/rooms")).toBe(1);

    finish(jsonResponse(room(makeGame()), 201));
    expect(await screen.findByRole("button", { name: "赞成" })).toBeInTheDocument();
  });

  it("returns to a game in progress after a reload", async () => {
    rememberSession();
    const server = serve({ "GET /api/games/g1": () => jsonResponse(makeGame()) });

    render(<App />);

    expect(screen.getByText("正在回到对局…")).toBeInTheDocument();
    expect(await screen.findByText("房间 ABC234")).toBeInTheDocument();
    expect(server.calls[0].init?.headers).toEqual({ Authorization: "Bearer tok" });
  });

  it("falls back to the lobby when the remembered game is gone", async () => {
    rememberSession();
    serve({
      ...HEALTH,
      "GET /api/games/g1": () => jsonResponse({ code: "invalid_token", message: "x" }, 401),
    });

    render(<App />);

    expect(await screen.findByRole("button", { name: "创建对局" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("avalon.session")).toBeNull();
  });

  it("submits an action with the version it was made for and shows the result", async () => {
    rememberSession();
    const next = makeGame({
      version: 14,
      phase: "mission_vote",
      proposed_team: [],
      legal_actions: [legal("vote_mission")],
    });
    const server = serve({
      "GET /api/games/g1": () => jsonResponse(makeGame()),
      "POST /api/games/g1/actions": () => jsonResponse(next),
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "赞成" }));

    expect(await screen.findByRole("button", { name: "任务成功" })).toBeInTheDocument();
    expect(server.body("POST /api/games/g1/actions")).toEqual({
      type: "vote_team",
      approve: true,
      expected_version: 8,
    });
  });

  it("ignores a second click while the first action is still being sent", async () => {
    rememberSession();
    let finish: (response: Response) => void = () => undefined;
    const server = serve({
      "GET /api/games/g1": () => jsonResponse(makeGame()),
      "POST /api/games/g1/actions": () => new Promise<Response>((resolve) => (finish = resolve)),
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "赞成" }));
    fireEvent.click(screen.getByRole("button", { name: "反对" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "赞成" })).toBeDisabled());
    expect(server.count("POST /api/games/g1/actions")).toBe(1);

    finish(jsonResponse(makeGame({ version: 9, legal_actions: [] })));
    expect(await screen.findByText("等待其他玩家行动…")).toBeInTheDocument();
  });

  it("refreshes the game and explains when the position has changed", async () => {
    rememberSession();
    const moved = makeGame({
      version: 20,
      phase: "mission_vote",
      proposed_team: [],
      legal_actions: [legal("vote_mission")],
    });
    let reads = 0;
    serve({
      "GET /api/games/g1": () => jsonResponse(reads++ === 0 ? makeGame() : moved),
      "POST /api/games/g1/actions": () =>
        jsonResponse({ code: "stale_version", message: "stale" }, 409),
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "赞成" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("局面已经变化");
    expect(screen.getByRole("button", { name: "任务成功" })).toBeEnabled();
  });

  it("keeps the game on screen when an action is refused", async () => {
    rememberSession();
    serve({
      "GET /api/games/g1": () => jsonResponse(makeGame()),
      "POST /api/games/g1/actions": () =>
        jsonResponse({ code: "something_new", message: "not allowed" }, 422),
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "赞成" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("操作失败：not allowed");
    expect(screen.getByRole("button", { name: "赞成" })).toBeEnabled();
  });

  it("forgets the session when you leave the game", async () => {
    rememberSession();
    serve({ ...HEALTH, "GET /api/games/g1": () => jsonResponse(makeGame()) });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "离开对局" }));

    expect(await screen.findByRole("button", { name: "创建对局" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("avalon.session")).toBeNull();
  });
});
