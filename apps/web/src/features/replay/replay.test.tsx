import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../../App";
import type { Game, LogEntry, Replay, Turn } from "../../api/client";
import { jsonResponse, makeGame, makePlayers } from "../../test/fixtures";
import { loadHistory, rememberGame } from "../../session";
import { LobbyPage } from "../lobby/LobbyPage";
import { buildSteps } from "../game/playback";
import { ReplayPage, turnsBehind } from "./ReplayPage";

const ROLES = ["merlin", "assassin", "loyal_servant", "minion", "loyal_servant"] as const;

const LOG: LogEntry[] = [
  { version: 2, kind: "mission_started", mission: 1, leader: "p2" },
  { version: 3, kind: "team_proposed", mission: 1, proposal: 1, leader: "p2", team: ["p2", "p3"] },
  { version: 4, kind: "speech", mission: 1, proposal: 1, player: "p2", text: "我带上 Lancelot。", suspects: [] },
  { version: 5, kind: "speech", mission: 1, proposal: 1, player: "p3", text: "", suspects: [] },
  { version: 6, kind: "speech", mission: 1, proposal: 1, player: "p4", text: "可以。", suspects: [] },
  { version: 7, kind: "speech", mission: 1, proposal: 1, player: "p5", text: "赞成。", suspects: [] },
  { version: 8, kind: "speech", mission: 1, proposal: 1, player: "p1", text: "我同意。", suspects: [] },
  {
    version: 13,
    kind: "team_vote",
    mission: 1,
    proposal: 1,
    approved: true,
    approvals: ["p1", "p2", "p3", "p4", "p5"],
    rejections: [],
  },
  { version: 16, kind: "mission_result", mission: 1, outcome: "fail", fail_votes: 1 },
  { version: 40, kind: "game_finished", winner: "evil", reason: "missions_failed" },
];

function turn(overrides: Partial<Turn>): Turn {
  return {
    version: 4,
    player_id: "p2",
    driver: "codex",
    source: "model",
    fallback_reason: null,
    attempts: 1,
    duration_ms: 5200,
    input_tokens: 0,
    output_tokens: 3900,
    observation: { you: { role: "assassin" } },
    exchanges: [
      {
        answer: {
          action: "speak",
          speech: "我带上 Lancelot。",
          inner: "Lancelot 是好人，带上他显得我坦荡。",
          note: "",
        },
      },
    ],
    ...overrides,
  };
}

const TURNS: Turn[] = [
  turn({}),
  turn({
    version: 10,
    exchanges: [{ answer: { action: "vote_team", approve: true } }],
  }),
  turn({
    version: 15,
    source: "fallback",
    fallback_reason: "timeout",
    exchanges: [{ error: "timeout" }],
    observation: null,
  }),
];

function finishedGame(overrides: Partial<Game> = {}): Game {
  return makeGame({
    phase: "finished",
    winner: "evil",
    win_reason: "missions_failed",
    legal_actions: [],
    log: LOG,
    players: makePlayers().map((player, seat) => ({
      ...player,
      role: ROLES[seat],
      alignment: ROLES[seat] === "assassin" || ROLES[seat] === "minion" ? "evil" : "good",
      agent: seat === 1 ? "llm" : player.agent,
      driver: seat === 1 ? "codex" : null,
    })),
    thoughts: [{ version: 4, player_id: "p2", text: "带上好人掩护自己。" }],
    ...overrides,
  });
}

const REPLAY: Replay = { game: finishedGame(), turns: TURNS };
const seat = (name: string) => screen.getByText(name, { selector: ".seat__name" }).closest("li") as HTMLElement;

describe("replaying a finished game", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts from the deal with every role on the table, and plays on by itself", () => {
    render(<ReplayPage replay={REPLAY} onLeave={() => undefined} />);

    expect(screen.getByText("第 0/12 步")).toBeInTheDocument();
    expect(within(seat("Gawain")).getByText("刺客")).toBeInTheDocument();
    expect(within(seat("Adam")).getByText("梅林")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "邪恶方获胜" })).not.toBeInTheDocument();

    act(() => vi.advanceTimersByTime(300));
    expect(screen.getByRole("heading", { level: 1, name: "任务 1 开始" })).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(1600));
    expect(screen.getByRole("heading", { level: 1, name: "Gawain 提名了队伍" })).toBeInTheDocument();
  });

  it("shows what the model saw and answered behind the step on show", () => {
    render(<ReplayPage replay={REPLAY} onLeave={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "暂停" }));
    fireEvent.change(screen.getByLabelText("回放进度"), { target: { value: 3 } });

    const turns = screen.getByRole("region", { name: "这一步背后的模型回合" });
    expect(within(turns).getByText("模型作答")).toBeInTheDocument();
    expect(within(turns).getByText("Lancelot 是好人，带上他显得我坦荡。")).toBeInTheDocument();
    expect(within(turns).getByText("模型看到的全部内容")).toBeInTheDocument();
    expect(screen.getByText("心声：带上好人掩护自己。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(within(turns).getByText(/这一步没有模型参与/)).toBeInTheDocument();
  });

  it("files a vote's hidden ballots under the step that reveals them", () => {
    const steps = buildSteps(REPLAY.game);
    const vote = steps.findIndex((step) => step.kind === "team_vote") + 1;
    const result = steps.findIndex((step) => step.kind === "mission_result") + 1;

    expect(turnsBehind(steps, vote, TURNS).map((t) => t.version)).toEqual([10]);
    expect(turnsBehind(steps, vote + 1, TURNS)).toEqual([]);
    expect(turnsBehind(steps, result, TURNS).map((t) => t.source)).toEqual(["fallback"]);
    expect(turnsBehind(steps, 0, TURNS)).toEqual([]);
  });

  it("can be paused, stepped back and forth, and jumped to the end", () => {
    render(<ReplayPage replay={REPLAY} onLeave={() => undefined} />);

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));
    act(() => vi.advanceTimersByTime(10000));
    expect(screen.getByText("第 0/12 步")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.click(screen.getByRole("button", { name: "上一步" }));
    expect(screen.getByText("第 1/12 步")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "跳到结局" }));
    expect(screen.getByRole("region", { name: "邪恶方获胜" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新播放" })).toBeInTheDocument();
    const totals = screen.getByRole("region", { name: "整局模型统计" });
    expect(within(totals).getByRole("row", { name: /Codex 3 1/ })).toBeInTheDocument();
  });

  it("plays faster at a higher speed", () => {
    render(<ReplayPage replay={REPLAY} onLeave={() => undefined} />);
    fireEvent.change(screen.getByLabelText("播放速度"), { target: { value: "4" } });

    act(() => vi.advanceTimersByTime(300));
    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByText("第 2/12 步")).toBeInTheDocument();
  });
});

describe("the games kept in this browser", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  const game = (gameId: string) => ({
    gameId,
    token: `tok-${gameId}`,
    createdAt: "2026-11-22T10:05:00.000Z",
    playerCount: 7,
    nickname: "Adam",
    spectate: false,
  });

  it("keeps the newest first, each game once", () => {
    rememberGame(game("a"));
    rememberGame(game("b"));
    rememberGame(game("a"));

    expect(loadHistory().map((past) => past.gameId)).toEqual(["a", "b"]);
  });

  it("ignores whatever else is in storage", () => {
    window.localStorage.setItem("avalon.history", JSON.stringify([{ gameId: 3 }, game("c")]));

    expect(loadHistory().map((past) => past.gameId)).toEqual(["c"]);
  });

  it("are listed in the lobby, each with a replay button", () => {
    const onReplay = vi.fn();
    render(
      <LobbyPage
        creating={false}
        error={null}
        onCreate={() => undefined}
        history={[game("a")]}
        onReplay={onReplay}
      />,
    );

    const list = screen.getByRole("region", { name: "最近的对局" });
    fireEvent.click(within(list).getByRole("button", { name: /回放 .* 的 7 人局/ }));

    expect(onReplay).toHaveBeenCalledWith(game("a"));
  });
});

describe("eleven and twelve at the table", () => {
  it("are offered in the lobby, with the house rules explained", () => {
    const onCreate = vi.fn();
    render(<LobbyPage creating={false} error={null} onCreate={onCreate} />);

    expect(screen.queryByText(/扩展规则/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("12 人"));
    expect(screen.getByText(/11–12 人用扩展规则/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("昵称"), { target: { value: "Adam" } });
    fireEvent.click(screen.getByRole("button", { name: "创建对局" }));
    expect(onCreate.mock.calls[0][1]).toBe(12);
    expect(onCreate.mock.calls[0][2].seats).toHaveLength(11);
  });
});

describe("the app opens a replay", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function serve(replay: Response) {
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
      if (url.endsWith("/health")) return jsonResponse({ status: "ok" });
      if (url.endsWith("/config")) return jsonResponse({});
      if (url.endsWith("/games/g1/replay")) return replay;
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("from the lobby's list of recent games", async () => {
    rememberGame({
      gameId: "g1",
      token: "tok",
      createdAt: "2026-11-22T10:05:00.000Z",
      playerCount: 5,
      nickname: "Adam",
      spectate: true,
    });
    const fetchMock = serve(jsonResponse(REPLAY));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /回放 .* 的 5 人局/ }));

    expect(await screen.findByRole("region", { name: "回放控制" })).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/replay"));
    expect(call?.[1]).toMatchObject({ headers: { Authorization: "Bearer tok" } });

    fireEvent.click(screen.getByRole("button", { name: "回到大厅" }));
    expect(screen.getByRole("heading", { name: "阿瓦隆 · 单人对局" })).toBeInTheDocument();
  });

  it("and offers to go back to a game that is still being played", async () => {
    rememberGame({
      gameId: "g1",
      token: "tok",
      createdAt: "2026-11-22T10:05:00.000Z",
      playerCount: 5,
      nickname: "Adam",
      spectate: false,
    });
    serve(jsonResponse({ code: "game_not_finished", message: "not yet" }, 409));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /回放/ }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("还没结束"));
    expect(screen.getByRole("button", { name: "回到这一局" })).toBeInTheDocument();
  });
});
