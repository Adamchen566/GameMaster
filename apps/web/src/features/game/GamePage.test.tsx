import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Game } from "../../api/client";
import { legal, makeGame, makePlayers } from "../../test/fixtures";
import { GamePage, seatPosition } from "./GamePage";
import { ROLE_NAMES } from "./labels";

function renderGame(game: Game, props: Partial<Parameters<typeof GamePage>[0]> = {}) {
  const handlers = { onAction: vi.fn(), onToggleTeam: vi.fn(), onLeave: vi.fn() };
  render(
    <GamePage game={game} pending={false} error={null} selectedTeam={[]} {...handlers} {...props} />,
  );
  return handlers;
}

function asLeader(): Game {
  return makeGame({
    phase: "team_proposal",
    proposed_team: [],
    team_voted: [],
    legal_actions: [legal("propose_team", { team_size: 2, targets: ["p1", "p2", "p3", "p4", "p5"] })],
  });
}

describe("GamePage", () => {
  it("shows the room, the phase and your own secret role", () => {
    renderGame(makeGame());

    expect(screen.getByText("房间 ABC234")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("组队投票");
    const role = screen.getByRole("region", { name: "你的身份" });
    expect(within(role).getByText("亚瑟的忠臣")).toBeInTheDocument();
    expect(within(role).getByText("正义方")).toBeInTheDocument();
  });

  it("never renders a role the server did not reveal", () => {
    renderGame(makeGame());

    const hidden = Object.entries(ROLE_NAMES)
      .filter(([role]) => role !== "loyal_servant")
      .map(([, name]) => name);
    for (const name of hidden) {
      expect(screen.queryByText(name)).not.toBeInTheDocument();
    }
    expect(screen.queryByText(/你知道：/)).not.toBeInTheDocument();
  });

  it("shows what your role lets you know about other players", () => {
    const players = makePlayers();
    players[2] = { ...players[2], seen_as: "evil" };

    renderGame(makeGame({ players }));

    const row = screen.getByText("Lancelot").closest("li") as HTMLElement;
    expect(within(row).getByText("你知道：邪恶方")).toBeInTheDocument();
  });

  it("lets you approve or reject the proposed team", () => {
    const { onAction } = renderGame(makeGame());

    const actions = screen.getByRole("region", { name: "你的操作" });
    expect(within(actions).getByText("Gawain、Lancelot")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "赞成" }));
    fireEvent.click(screen.getByRole("button", { name: "反对" }));

    expect(onAction).toHaveBeenNthCalledWith(1, { type: "vote_team", approve: true });
    expect(onAction).toHaveBeenNthCalledWith(2, { type: "vote_team", approve: false });
  });

  it("disables every action button while a request is in flight", () => {
    renderGame(makeGame(), { pending: true });

    expect(screen.getByRole("button", { name: "赞成" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "反对" })).toBeDisabled();
  });

  it("offers only the actions the server lists as legal", () => {
    renderGame(makeGame({ legal_actions: [] }));

    expect(screen.queryByRole("button", { name: "赞成" })).not.toBeInTheDocument();
    expect(screen.getByText("等待其他玩家行动…")).toBeInTheDocument();
  });

  it("lets the host start the game from the lobby", () => {
    const { onAction } = renderGame(
      makeGame({ phase: "lobby", missions: [], proposed_team: [], legal_actions: [legal("start_game")] }),
    );

    fireEvent.click(screen.getByRole("button", { name: "开始游戏" }));

    expect(onAction).toHaveBeenCalledExactlyOnceWith({ type: "start_game" });
  });

  it("only submits a team of exactly the right size", () => {
    const { onAction, onToggleTeam } = renderGame(asLeader(), { selectedTeam: ["p1"] });

    const submit = screen.getByRole("button", { name: "提交队伍" });
    expect(submit).toBeDisabled();
    expect(screen.getByRole("button", { name: "Adam" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Tristan" }));
    expect(onToggleTeam).toHaveBeenCalledExactlyOnceWith("p4");
    expect(onAction).not.toHaveBeenCalled();
  });

  it("submits the selected team and blocks further picks once it is full", () => {
    const { onAction } = renderGame(asLeader(), { selectedTeam: ["p1", "p4"] });

    expect(screen.getByRole("button", { name: "Gawain" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Adam" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "提交队伍" }));

    expect(onAction).toHaveBeenCalledExactlyOnceWith({ type: "propose_team", team: ["p1", "p4"] });
  });

  it("gives a good player only the success card", () => {
    const { onAction } = renderGame(
      makeGame({ phase: "mission_vote", proposed_team: [], legal_actions: [legal("vote_mission")] }),
    );

    expect(screen.queryByRole("button", { name: "任务失败" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "任务成功" }));

    expect(onAction).toHaveBeenCalledExactlyOnceWith({ type: "vote_mission", success: true });
  });

  it("gives an evil player both cards", () => {
    const { onAction } = renderGame(
      makeGame({
        phase: "mission_vote",
        proposed_team: [],
        legal_actions: [legal("vote_mission", { can_fail: true })],
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "任务失败" }));

    expect(onAction).toHaveBeenCalledExactlyOnceWith({ type: "vote_mission", success: false });
  });

  it("makes the assassin pick a target before confirming", () => {
    const { onAction } = renderGame(
      makeGame({
        phase: "assassination",
        proposed_team: [],
        legal_actions: [legal("assassinate", { targets: ["p2", "p3", "p4", "p5"] })],
      }),
    );

    const confirm = screen.getByRole("button", { name: "确认刺杀" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Tristan" }));
    fireEvent.click(confirm);

    expect(onAction).toHaveBeenCalledExactlyOnceWith({ type: "assassinate", target_id: "p4" });
  });

  it("shows mission results, the two-fail mission and the rejection count", () => {
    const game = makeGame({ current_mission_number: 3, proposal_number: 3 });
    game.missions[0] = { ...game.missions[0], team: ["p1", "p2"], outcome: "success", fail_votes: 0 };
    game.missions[1] = { ...game.missions[1], team: ["p1", "p2", "p3"], outcome: "fail", fail_votes: 1 };
    game.missions[3] = { ...game.missions[3], fails_required: 2 };

    renderGame(game);

    const missions = screen.getByRole("region", { name: "任务" });
    const cards = within(missions).getAllByRole("listitem");
    expect(cards.map((card) => card.textContent)).toEqual([
      "任务 1成功0 张失败牌",
      "任务 2失败1 张失败牌",
      "任务 3未做进行中 · 2 人",
      "任务 4未做3 人 · 需 2 张失败",
      "任务 5未做3 人",
    ]);
    expect(cards[2]).toHaveAttribute("aria-current", "step");
    expect(cards[0]).not.toHaveAttribute("aria-current");
    expect(within(missions).getByText(/已否决 2\/5 次组队/)).toBeInTheDocument();
  });

  it("reveals the last team vote by name", () => {
    renderGame(
      makeGame({
        last_team_vote: {
          mission_number: 1,
          proposal_number: 2,
          team: ["p1", "p2"],
          approvals: ["p1", "p2", "p3"],
          rejections: ["p4", "p5"],
          approved: true,
        },
      }),
    );

    const vote = screen.getByRole("region", { name: "上一次组队投票：通过" });
    expect(within(vote).getByText("赞成：Adam、Gawain、Lancelot")).toBeInTheDocument();
    expect(within(vote).getByText("反对：Tristan、Galahad")).toBeInTheDocument();
  });

  it("shows an error from the last action", () => {
    renderGame(makeGame(), { error: "局面已经变化，画面已刷新，请重新操作。" });

    expect(screen.getByRole("alert")).toHaveTextContent("局面已经变化");
  });

  it("reveals every role and offers a new game when the game is over", () => {
    const roles = ["loyal_servant", "merlin", "assassin", "minion", "loyal_servant"] as const;
    const players = makePlayers().map((player, index) => ({
      ...player,
      role: roles[index],
      alignment: roles[index] === "assassin" || roles[index] === "minion" ? "evil" : "good",
    })) as Game["players"];
    const { onLeave } = renderGame(
      makeGame({
        phase: "finished",
        players,
        proposed_team: [],
        winner: "evil",
        win_reason: "merlin_assassinated",
        assassination_target_id: "p2",
        legal_actions: [],
      }),
    );

    expect(screen.getByRole("region", { name: "邪恶方获胜" })).toHaveTextContent(
      "梅林被刺客找到了",
    );
    const merlin = screen.getByText("Gawain").closest("li") as HTMLElement;
    expect(within(merlin).getByText("梅林")).toBeInTheDocument();
    expect(within(merlin).getByText("被刺杀")).toBeInTheDocument();
    expect(screen.getByText("刺客")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "你的身份" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "再来一局" }));
    expect(onLeave).toHaveBeenCalledOnce();
  });

  it("lets you leave at any time", () => {
    const { onLeave } = renderGame(makeGame());

    fireEvent.click(screen.getByRole("button", { name: "离开对局" }));

    expect(onLeave).toHaveBeenCalledOnce();
  });
});

function discussing(overrides: Partial<Game> = {}): Game {
  return makeGame({
    phase: "discussion",
    team_voted: [],
    speeches: [
      { player_id: "p2", text: "我选 Gawain 和 Lancelot。", suspects: [] },
      { player_id: "p3", text: "", suspects: [] },
      { player_id: "p4", text: "我会反对。", suspects: ["p3"] },
      { player_id: "p5", text: "可以接受。", suspects: [] },
    ],
    speaker_id: "p1",
    legal_actions: [legal("speak", { targets: ["p2", "p3", "p4", "p5"] })],
    ...overrides,
  });
}

describe("the round table", () => {
  it("puts you at the bottom and the others clockwise in seat order", () => {
    const you = seatPosition(0, 5);
    expect(you.left).toBeCloseTo(50);
    expect(you.top).toBeGreaterThan(85);

    // The next seat is to your left on screen, which is clockwise seen from above.
    expect(seatPosition(1, 5).left).toBeLessThan(40);
    expect(seatPosition(4, 5).left).toBeGreaterThan(60);

    // Someone sits straight across in an even game.
    const across = seatPosition(3, 6);
    expect(across.left).toBeCloseTo(50);
    expect(across.top).toBeLessThan(15);
  });

  it("seats every player once, each at its own place", () => {
    renderGame(makeGame());

    const seats = within(screen.getByRole("list", { name: "座位" })).getAllByRole("listitem");
    expect(seats.map((seat) => within(seat).getByText(/^[A-Z][a-z]+$/).textContent)).toEqual([
      "Adam",
      "Gawain",
      "Lancelot",
      "Tristan",
      "Galahad",
    ]);
    const places = new Set(seats.map((seat) => `${seat.style.left} ${seat.style.top}`));
    expect(places.size).toBe(5);
  });

  it("lays the five mission cards in the middle, undone until played", () => {
    renderGame(makeGame());

    const missions = screen.getByRole("region", { name: "任务" });
    expect(within(missions).getAllByRole("listitem")).toHaveLength(5);
    expect(within(missions).getAllByText("未做")).toHaveLength(5);
    expect(within(missions).getByText("提名队伍：")).toHaveTextContent("Gawain、Lancelot");
  });

  it("marks who is on the proposed team and who leads", () => {
    renderGame(makeGame());

    const gawain = screen.getByText("Gawain").closest("li") as HTMLElement;
    expect(within(gawain).getByText("队长")).toBeInTheDocument();
    expect(within(gawain).getByText("提名中")).toBeInTheDocument();
    const tristan = screen.getByText("Tristan").closest("li") as HTMLElement;
    expect(within(tristan).queryByText("提名中")).not.toBeInTheDocument();
  });

  it("shows how each seat voted last time while the next team is being chosen", () => {
    const game = asLeader();
    game.last_team_vote = {
      mission_number: 1,
      proposal_number: 1,
      team: ["p2", "p3"],
      approvals: ["p2", "p3"],
      rejections: ["p1", "p4", "p5"],
      approved: false,
    };
    renderGame(game);

    const seats = screen.getByRole("list", { name: "座位" });
    expect(within(seats).getAllByText("上轮赞成")).toHaveLength(2);
    expect(within(seats).getAllByText("上轮反对")).toHaveLength(3);
  });
});

describe("speaking", () => {
  it("names the phase and shows whose turn it is", () => {
    renderGame(discussing({ speaker_id: "p3", legal_actions: [] }));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("轮流发言");
    const lancelot = screen.getByText("Lancelot", { selector: ".seat__name" }).closest("li");
    expect(within(lancelot as HTMLElement).getByText("发言中")).toBeInTheDocument();
    expect(screen.getAllByText("发言中")).toHaveLength(1);
  });

  it("lists what was said in speaking order, with passes and accusations", () => {
    renderGame(discussing());

    const log = screen.getByRole("region", { name: "本轮发言" });
    const lines = within(log).getAllByRole("listitem");
    expect(lines.map((line) => line.textContent)).toEqual([
      "Gawain我选 Gawain 和 Lancelot。",
      "Lancelot（过）",
      "Tristan我会反对。点名怀疑：Lancelot",
      "Galahad可以接受。",
    ]);
  });

  it("shows each speech at the seat that made it", () => {
    renderGame(discussing());

    const tristan = screen.getByText("Tristan", { selector: ".seat__name" }).closest("li");
    expect((tristan as HTMLElement).querySelector(".seat__speech")).toHaveTextContent("我会反对。");
    const you = screen.getByText("Adam", { selector: ".seat__name" }).closest("li");
    expect((you as HTMLElement).querySelector(".seat__speech")).toBeNull();
  });

  it("sends your speech with the players you name", () => {
    const { onAction } = renderGame(discussing());

    fireEvent.change(screen.getByLabelText("你的发言"), { target: { value: "  我不信 Tristan。 " } });
    const suspects = screen.getByRole("group", { name: "点名怀疑（最多 3 人）" });
    fireEvent.click(within(suspects).getByRole("button", { name: "Tristan" }));
    fireEvent.click(screen.getByRole("button", { name: "发言" }));

    expect(onAction).toHaveBeenCalledExactlyOnceWith({
      type: "speak",
      text: "我不信 Tristan。",
      suspects: ["p4"],
    });
  });

  it("lets you pass without saying anything", () => {
    const { onAction } = renderGame(discussing());

    expect(screen.getByRole("button", { name: "发言" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "过" }));

    expect(onAction).toHaveBeenCalledExactlyOnceWith({ type: "speak", text: "", suspects: [] });
  });

  it("stops you from naming more than three players or yourself", () => {
    renderGame(discussing());

    const suspects = screen.getByRole("group", { name: "点名怀疑（最多 3 人）" });
    expect(within(suspects).queryByRole("button", { name: "Adam" })).not.toBeInTheDocument();
    for (const name of ["Gawain", "Lancelot", "Tristan"]) {
      fireEvent.click(within(suspects).getByRole("button", { name }));
    }

    expect(within(suspects).getByRole("button", { name: "Galahad" })).toBeDisabled();
    expect(within(suspects).getByRole("button", { name: "Gawain" })).toBeEnabled();
  });

  it("refuses a speech that is too long", () => {
    renderGame(discussing());

    fireEvent.change(screen.getByLabelText("你的发言"), { target: { value: "长".repeat(201) } });

    expect(screen.getByText("201/200 字")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发言" })).toBeDisabled();
    expect(screen.getByLabelText("你的发言")).toHaveAttribute("aria-invalid", "true");
  });

  it("tells the leader to explain the team", () => {
    const players = makePlayers().map((player) => ({ ...player, is_leader: player.id === "p1" }));
    renderGame(discussing({ leader_id: "p1", players, speeches: [] }));

    expect(screen.getByText(/说说你为什么选这支队伍/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "本轮发言" })).not.toBeInTheDocument();
  });

  it("freezes the form while the speech is being sent", () => {
    renderGame(discussing(), { pending: true });

    expect(screen.getByRole("button", { name: "过" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Tristan" })).toBeDisabled();
  });
});
