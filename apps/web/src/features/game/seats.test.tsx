import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Game, LogEntry, Persona, Player } from "../../api/client";
import { legal, makeGame, makePlayers } from "../../test/fixtures";
import { GamePage } from "./GamePage";
import { buildSteps, CATCH_UP_DELAY_MS, sceneAt, stepDuration } from "./playback";

const GAWAIN: Persona = {
  title: "直率的急先锋",
  manner: "热血、直率。",
  color: "#e0763c",
  pitch: 0.9,
  rate: 1.15,
};

function page(game: Game, onAction = vi.fn()) {
  return (
    <GamePage
      game={game}
      pending={false}
      error={null}
      selectedTeam={[]}
      onToggleTeam={() => undefined}
      onAction={onAction}
      onLeave={() => undefined}
    />
  );
}

function players(changes: Record<string, Partial<Player>> = {}): Player[] {
  return makePlayers().map((player) => ({ ...player, ...changes[player.id] }));
}

const seat = (name: string) => screen.getByText(name).closest("li") as HTMLElement;

describe("who is in each seat", () => {
  it("names the model that plays a seat and shows the character's colour", () => {
    render(
      page(
        makeGame({
          players: players({
            p2: { agent: "llm", driver: "deepseek", persona: GAWAIN },
            p3: { agent: "llm", driver: "claude_code" },
            p4: { agent: "llm", driver: null },
          }),
        }),
      ),
    );

    expect(within(seat("Gawain")).getByText("DeepSeek")).toBeInTheDocument();
    expect(within(seat("Lancelot")).getByText("Claude Code")).toBeInTheDocument();
    expect(within(seat("Tristan")).getByText("AI")).toBeInTheDocument();
    expect(within(seat("Galahad")).getByText("机器人")).toBeInTheDocument();
    expect(seat("Gawain")).toHaveAttribute("title", "直率的急先锋：热血、直率。");
    expect(seat("Gawain").style.borderTopColor).not.toBe("");
  });

  it("marks your own name when you choose the team, because you may pick yourself", () => {
    render(
      page(
        makeGame({
          phase: "team_proposal",
          leader_id: "p1",
          proposed_team: [],
          team_voted: [],
          legal_actions: [
            legal("propose_team", { team_size: 2, targets: ["p1", "p2", "p3", "p4", "p5"] }),
          ],
        }),
      ),
    );

    const choices = screen.getByRole("group", { name: "选择任务成员" });
    expect(within(choices).getByRole("button", { name: "Adam（你）" })).toBeEnabled();
    expect(screen.getByText(/可以选你自己/)).toBeInTheDocument();
  });
});

describe("watching from outside the table", () => {
  const watched = makeGame({
    spectator: true,
    you_id: "",
    legal_actions: [],
    players: players({
      p1: { is_you: false, is_bot: true, agent: "random", role: "merlin", alignment: "good" },
      p2: { role: "assassin", alignment: "evil" },
      p3: { role: "loyal_servant", alignment: "good" },
      p4: { role: "minion", alignment: "evil" },
      p5: { role: "loyal_servant", alignment: "good" },
    }),
  });

  it("shows every role, no seat of your own and nothing to do", () => {
    render(page(watched));

    expect(screen.getByText(/观战中，所有身份对你可见/)).toBeInTheDocument();
    expect(within(seat("Adam")).getByText("梅林")).toBeInTheDocument();
    expect(within(seat("Gawain")).getByText("刺客")).toBeInTheDocument();
    expect(screen.queryByText("你")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "你的身份" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("你在观战");
    expect(screen.queryByRole("button", { name: "赞成" })).not.toBeInTheDocument();
  });

  it("lets the spectator open the game they set up", () => {
    const onAction = vi.fn();
    render(page({ ...watched, phase: "lobby", legal_actions: [legal("start_game")] }, onAction));

    expect(screen.getByText(/这一桌全是 AI，你来观战/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始游戏" }));

    expect(onAction).toHaveBeenCalledWith({ type: "start_game" });
  });

  it("keeps the roles on the table while a spectated game is replayed", () => {
    const log: LogEntry[] = [
      { version: 2, kind: "mission_started", mission: 1, leader: "p2" },
      { version: 3, kind: "team_proposed", mission: 1, proposal: 1, leader: "p2", team: ["p2", "p3"] },
    ];
    const game = { ...watched, log };
    const scene = sceneAt(game, buildSteps(game), 1);

    expect(scene.players.every((player) => player.role !== null)).toBe(true);
  });
});

describe("what the AI seats really think", () => {
  const speech: LogEntry = {
    version: 4,
    kind: "speech",
    mission: 1,
    proposal: 1,
    player: "p2",
    text: "这一队我放心。",
    suspects: [],
  };
  const log: LogEntry[] = [
    { version: 2, kind: "mission_started", mission: 1, leader: "p2" },
    { version: 3, kind: "team_proposed", mission: 1, proposal: 1, leader: "p2", team: ["p2", "p3"] },
    speech,
  ];
  const thoughts = [
    { version: 3, player_id: "p2", text: "我是邪恶方，同伴是 Tristan。" },
    { version: 4, player_id: "p2", text: "队里有同伴，我要让它通过。" },
  ];

  it("shows nothing when the server sent no thoughts", () => {
    render(page(makeGame({ log })));

    expect(screen.queryByRole("region", { name: "心声" })).not.toBeInTheDocument();
    expect(screen.queryByText(/心声：/)).not.toBeInTheDocument();
  });

  it("shows a spectator the thought behind the speech on the table, newest first below", () => {
    render(page(makeGame({ spectator: true, you_id: "", legal_actions: [], log, thoughts })));

    expect(screen.getByText("心声：队里有同伴，我要让它通过。")).toBeInTheDocument();
    const list = within(screen.getByRole("region", { name: "心声" })).getAllByRole("listitem");
    expect(list.map((item) => item.textContent)).toEqual([
      "Gawain队里有同伴，我要让它通过。",
      "Gawain我是邪恶方，同伴是 Tristan。",
    ]);
  });

  it("becomes a review in order once the game is over", () => {
    const over: LogEntry = { version: 9, kind: "game_finished", winner: "evil", reason: "missions_failed" };
    render(
      page(
        makeGame({
          phase: "finished",
          winner: "evil",
          win_reason: "missions_failed",
          legal_actions: [],
          log: [...log, over],
          thoughts,
        }),
      ),
    );

    const review = screen.getByRole("region", { name: "复盘：每个 AI 当时的真实想法" });
    expect(within(review).getAllByRole("listitem")[0]).toHaveTextContent("我是邪恶方");
  });

  describe("while a spectated game is replayed", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("does not show a thought before its moment", () => {
      const before = makeGame({
        spectator: true,
        you_id: "",
        phase: "lobby",
        version: 0,
        legal_actions: [legal("start_game")],
      });
      const view = render(page(before));
      view.rerender(page({ ...before, phase: "discussion", legal_actions: [], log, thoughts }));

      act(() => vi.advanceTimersByTime(CATCH_UP_DELAY_MS));
      expect(screen.getByText("任务 1 开始")).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "心声" })).not.toBeInTheDocument();

      act(() => vi.advanceTimersByTime(1600));
      expect(within(screen.getByRole("region", { name: "心声" })).getAllByRole("listitem")).toHaveLength(1);
      expect(screen.queryByText(/心声：队里有同伴/)).not.toBeInTheDocument();

      act(() => vi.advanceTimersByTime(2000));
      expect(screen.getByText("心声：队里有同伴，我要让它通过。")).toBeInTheDocument();
    });
  });
});

describe("the ballots", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("are drawn from every seat to the middle while the vote is read out", () => {
    const talk: LogEntry[] = [
      { version: 2, kind: "mission_started", mission: 1, leader: "p2" },
      { version: 3, kind: "team_proposed", mission: 1, proposal: 1, leader: "p2", team: ["p2", "p3"] },
    ];
    const vote: LogEntry = {
      version: 14,
      kind: "team_vote",
      mission: 1,
      proposal: 1,
      approved: false,
      approvals: ["p2", "p3"],
      rejections: ["p1", "p4", "p5"],
    };
    const before = makeGame({ log: talk });
    const view = render(page(before));
    expect(document.querySelectorAll(".ballot")).toHaveLength(0);

    view.rerender(page(makeGame({ log: [...talk, vote], phase: "team_proposal", legal_actions: [] })));
    act(() => vi.advanceTimersByTime(CATCH_UP_DELAY_MS));

    expect(document.querySelectorAll(".ballot--yes")).toHaveLength(2);
    expect(document.querySelectorAll(".ballot--no")).toHaveLength(3);
  });
});

describe("reading aloud", () => {
  it("gives a spoken speech longer on the table than a silent one", () => {
    const speech: LogEntry = {
      version: 4,
      kind: "speech",
      mission: 1,
      proposal: 1,
      player: "p2",
      text: "这一队里有上一轮任务失败时在场的人，我不放心。",
      suspects: [],
    };

    expect(stepDuration(speech, true)).toBeGreaterThan(stepDuration(speech));
    expect(stepDuration({ ...speech, text: "" }, true)).toBe(stepDuration({ ...speech, text: "" }));
  });

  it("is not offered where the browser cannot speak", () => {
    render(page(makeGame()));

    expect(screen.queryByRole("button", { name: /朗读/ })).not.toBeInTheDocument();
  });

  describe("where the browser can speak", () => {
    const speak = vi.fn();
    const cancel = vi.fn();

    beforeEach(() => {
      vi.useFakeTimers();
      window.localStorage.clear();
      vi.stubGlobal("speechSynthesis", { speak, cancel });
      vi.stubGlobal(
        "SpeechSynthesisUtterance",
        class {
          lang = "";
          pitch = 1;
          rate = 1;
          constructor(readonly text: string) {}
        },
      );
    });

    afterEach(() => {
      vi.useRealTimers();
      vi.unstubAllGlobals();
      speak.mockClear();
      cancel.mockClear();
    });

    it("stays silent until switched on, then reads each new line in the speaker's voice", () => {
      const lobby = makeGame({ phase: "lobby", version: 0, legal_actions: [legal("start_game")] });
      const log: LogEntry[] = [
        { version: 2, kind: "mission_started", mission: 1, leader: "p2" },
        { version: 3, kind: "team_proposed", mission: 1, proposal: 1, leader: "p2", team: ["p2", "p3"] },
        { version: 4, kind: "speech", mission: 1, proposal: 1, player: "p2", text: "我带上 Lancelot。", suspects: [] },
      ];
      const view = render(page(lobby));

      fireEvent.click(screen.getByRole("button", { name: "朗读：关" }));
      expect(screen.getByRole("button", { name: "朗读：开" })).toHaveAttribute("aria-pressed", "true");
      expect(window.localStorage.getItem("avalon.readAloud")).toBe("on");
      expect(speak).not.toHaveBeenCalled();

      view.rerender(
        page(
          makeGame({
            phase: "discussion",
            legal_actions: [],
            log,
            players: players({ p2: { persona: GAWAIN } }),
          }),
        ),
      );
      act(() => vi.advanceTimersByTime(CATCH_UP_DELAY_MS));
      expect(speak).toHaveBeenLastCalledWith(expect.objectContaining({ text: "任务 1 开始" }));

      act(() => vi.advanceTimersByTime(1600));
      act(() => vi.advanceTimersByTime(2000));
      expect(speak).toHaveBeenLastCalledWith(
        expect.objectContaining({ text: "我带上 Lancelot。", pitch: 0.9, rate: 1.15, lang: "zh-CN" }),
      );
    });
  });
});
