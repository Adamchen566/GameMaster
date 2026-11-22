import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Game } from "../../api/client";
import { legal, makeGame, makePlayers } from "../../test/fixtures";
import { GamePage } from "./GamePage";
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

    expect(screen.getByText("Gawain、Lancelot")).toBeInTheDocument();
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
    expect(within(missions).getByText("✓ 成功（0 张失败）")).toBeInTheDocument();
    expect(within(missions).getByText("✗ 失败（1 张失败）")).toBeInTheDocument();
    expect(within(missions).getByText("进行中")).toBeInTheDocument();
    expect(within(missions).getByText("需 2 张失败")).toBeInTheDocument();
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
