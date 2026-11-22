import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Game, LogEntry } from "../../api/client";
import { legal, makeGame } from "../../test/fixtures";
import { GamePage } from "./GamePage";
import { buildSteps, CATCH_UP_DELAY_MS, sceneAt, stepDuration } from "./playback";

const EVERYONE = ["p2", "p3", "p4", "p5", "p1"];

/** Mission 1: Gawain (p2) leads, proposes himself and Lancelot, and the table talks. */
function round(spoken: number): LogEntry[] {
  return [
    { version: 2, kind: "mission_started", mission: 1, leader: "p2" },
    { version: 3, kind: "team_proposed", mission: 1, proposal: 1, leader: "p2", team: ["p2", "p3"] },
    ...EVERYONE.slice(0, spoken).map(
      (player, index): LogEntry => ({
        version: 4 + index,
        kind: "speech",
        mission: 1,
        proposal: 1,
        player,
        text: index === 0 ? "我带上 Lancelot。" : "",
        suspects: index === 1 ? ["p4"] : [],
      }),
    ),
  ];
}

const APPROVED: LogEntry = {
  version: 14,
  kind: "team_vote",
  mission: 1,
  proposal: 1,
  approved: true,
  approvals: ["p1", "p2", "p3"],
  rejections: ["p4", "p5"],
};
const REJECTED: LogEntry = { ...APPROVED, approved: false };
const FAILED: LogEntry = {
  version: 17,
  kind: "mission_result",
  mission: 1,
  outcome: "fail",
  fail_votes: 1,
};

function gameWith(log: LogEntry[], overrides: Partial<Game> = {}): Game {
  return makeGame({ log, version: log.at(-1)?.version ?? 0, ...overrides });
}

describe("buildSteps", () => {
  it("keeps the public record in order", () => {
    const steps = buildSteps(gameWith(round(2)));

    expect(steps.map((step) => step.kind)).toEqual([
      "mission_started",
      "team_proposed",
      "speech",
      "speech",
    ]);
  });

  it("adds a beat for the vote opening once everyone has spoken", () => {
    const steps = buildSteps(gameWith(round(5)));

    expect(steps.at(-1)).toEqual({ kind: "voting_opens", version: 8, team: ["p2", "p3"] });
  });

  it("adds a beat for the team leaving after an approved vote only", () => {
    const approved = buildSteps(gameWith([...round(5), APPROVED]));
    const rejected = buildSteps(gameWith([...round(5), REJECTED]));

    expect(approved.at(-1)).toMatchObject({ kind: "team_departs", mission: 1, team: ["p2", "p3"] });
    expect(rejected.at(-1)?.kind).toBe("team_vote");
  });

  it("gives an earlier response's steps as a prefix of a later one", () => {
    const earlier = buildSteps(gameWith(round(5)));
    const later = buildSteps(gameWith([...round(5), APPROVED, FAILED]));

    expect(later.slice(0, earlier.length)).toEqual(earlier);
  });
});

describe("stepDuration", () => {
  it("gives a speech more time the longer it is, within a limit", () => {
    const say = (text: string) =>
      stepDuration({ ...round(1)[2], text } as Extract<LogEntry, { kind: "speech" }>);

    expect(say("")).toBeLessThan(say("好。"));
    expect(say("好。")).toBeLessThan(say("这一队里有上一轮任务失败时在场的人，我不放心。"));
    expect(say("很".repeat(200))).toBe(5000);
  });
});

describe("sceneAt", () => {
  const finished = gameWith([...round(5), APPROVED, FAILED], {
    phase: "mission_vote",
    legal_actions: [legal("vote_mission")],
    missions: makeGame().missions.map((mission) =>
      mission.number === 1
        ? { ...mission, team: ["p2", "p3"], outcome: "fail", fail_votes: 1 }
        : mission,
    ),
  });
  const steps = buildSteps(finished);
  const at = (kind: string, nth = 0) =>
    steps.findIndex((step, index) => step.kind === kind && nth-- === 0 && index >= 0) + 1;

  it("is the real game once every step has been shown", () => {
    expect(sceneAt(finished, steps, steps.length)).toBe(finished);
  });

  it("shows the lobby before the first step", () => {
    expect(sceneAt(finished, steps, 0).phase).toBe("lobby");
  });

  it("offers no action from a past position", () => {
    for (let shown = 0; shown < steps.length; shown += 1) {
      expect(sceneAt(finished, steps, shown).legal_actions).toEqual([]);
    }
  });

  it("names the leader and opens the discussion when the team is proposed", () => {
    const scene = sceneAt(finished, steps, at("team_proposed"));

    expect(scene.phase).toBe("discussion");
    expect(scene.leader_id).toBe("p2");
    expect(scene.players.find((player) => player.is_leader)?.id).toBe("p2");
    expect(scene.proposed_team).toEqual(["p2", "p3"]);
    expect(scene.speeches).toEqual([]);
  });

  it("reveals the speeches one at a time, marking who is speaking", () => {
    const first = sceneAt(finished, steps, at("speech"));
    const second = sceneAt(finished, steps, at("speech", 1));

    expect(first.speeches.map((speech) => speech.player_id)).toEqual(["p2"]);
    expect(first.speaker_id).toBe("p2");
    expect(second.speeches.map((speech) => speech.player_id)).toEqual(["p2", "p3"]);
    expect(second.speeches[1].suspects).toEqual(["p4"]);
    expect(second.speaker_id).toBe("p3");
  });

  it("opens the vote only after the last speech", () => {
    expect(sceneAt(finished, steps, at("speech", 4)).phase).toBe("discussion");
    expect(sceneAt(finished, steps, at("voting_opens")).phase).toBe("team_vote");
  });

  it("does not show a mission result before it is read out", () => {
    const voted = sceneAt(finished, steps, at("team_vote"));

    expect(voted.phase).toBe("mission_vote");
    expect(voted.last_team_vote).toMatchObject({ approved: true, team: ["p2", "p3"] });
    expect(voted.missions[0]).toMatchObject({ team: ["p2", "p3"], outcome: null, fail_votes: null });
  });

  it("passes the lead clockwise after a rejected team", () => {
    const rejected = gameWith([
      ...round(5),
      REJECTED,
      { version: 15, kind: "team_proposed", mission: 1, proposal: 2, leader: "p3", team: ["p3", "p1"] },
    ]);
    const rejectedSteps = buildSteps(rejected);
    const scene = sceneAt(rejected, rejectedSteps, rejectedSteps.length - 1);

    expect(scene.phase).toBe("team_proposal");
    expect(scene.leader_id).toBe("p3");
    expect(scene.proposal_number).toBe(2);
    expect(scene.proposed_team).toEqual([]);
  });

  it("keeps the roles hidden until the end, even when the final position reveals them", () => {
    const over = gameWith(
      [...round(5), APPROVED, FAILED, { version: 18, kind: "game_finished", winner: "evil", reason: "missions_failed" }],
      {
        phase: "finished",
        winner: "evil",
        win_reason: "missions_failed",
        players: makeGame().players.map((player) => ({
          ...player,
          role: "minion",
          alignment: "evil",
        })),
      },
    );
    const overSteps = buildSteps(over);
    const before = sceneAt(over, overSteps, overSteps.length - 1);

    expect(before.winner).toBeNull();
    expect(before.phase).not.toBe("finished");
    expect(before.players.filter((player) => player.role !== null).map((p) => p.id)).toEqual(["p1"]);
  });
});

describe("a table that plays one step at a time", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function page(game: Game) {
    return (
      <GamePage
        game={game}
        pending={false}
        error={null}
        selectedTeam={[]}
        onToggleTeam={() => undefined}
        onAction={() => undefined}
        onLeave={() => undefined}
      />
    );
  }

  const lobby = makeGame({
    phase: "lobby",
    version: 0,
    leader_id: null,
    proposed_team: [],
    team_voted: [],
    current_mission_number: null,
    proposal_number: null,
    legal_actions: [legal("start_game")],
  });
  const talking = gameWith(round(4), {
    phase: "discussion",
    speaker_id: "p1",
    team_voted: [],
    speeches: round(4)
      .filter((entry) => entry.kind === "speech")
      .map((entry) => ({ player_id: entry.player, text: entry.text, suspects: entry.suspects })),
    legal_actions: [legal("speak", { targets: ["p2", "p3", "p4", "p5"] })],
  });
  const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms));
  const spoken = () => within(screen.getByRole("region", { name: "本轮发言" })).getAllByRole("listitem");

  it("does not replay a game that is opened in the middle", () => {
    render(page(talking));

    expect(spoken()).toHaveLength(4);
    expect(screen.getByRole("button", { name: "发言" })).toBeInTheDocument();
  });

  it("walks from the start to your turn, one speech at a time", () => {
    const view = render(page(lobby));
    view.rerender(page(talking));

    // Nothing has moved yet: the table is still as it was.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("等待开始");
    expect(screen.queryByRole("button", { name: "发言" })).not.toBeInTheDocument();

    advance(CATCH_UP_DELAY_MS);
    expect(screen.getByText("任务 1 开始")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("队长组队");

    advance(1600);
    expect(screen.getByText("Gawain 提名了队伍")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "本轮发言" })).not.toBeInTheDocument();

    advance(2000);
    expect(screen.getByText("Gawain 发言")).toBeInTheDocument();
    expect(spoken()).toHaveLength(1);

    advance(5000);
    expect(screen.getByText("Lancelot 发言")).toBeInTheDocument();
    expect(spoken()).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "发言" })).not.toBeInTheDocument();

    advance(800);
    advance(800);
    expect(spoken()).toHaveLength(4);
    // Caught up: now it is your turn.
    expect(screen.getByRole("button", { name: "发言" })).toBeInTheDocument();
  });

  it("is not restarted by a poll that brings nothing new", () => {
    const view = render(page(lobby));
    view.rerender(page(talking));
    advance(CATCH_UP_DELAY_MS);

    advance(1500);
    view.rerender(page({ ...talking }));
    advance(100);

    expect(screen.getByText("Gawain 提名了队伍")).toBeInTheDocument();
  });

  it("can be skipped", () => {
    const view = render(page(lobby));
    view.rerender(page(talking));
    advance(CATCH_UP_DELAY_MS);

    act(() => screen.getByRole("button", { name: "跳过，直接看现在" }).click());

    expect(spoken()).toHaveLength(4);
    expect(screen.getByRole("button", { name: "发言" })).toBeInTheDocument();
  });

  it("turns the ballots over before the team leaves", () => {
    const voting = gameWith(round(5), { phase: "team_vote", legal_actions: [legal("vote_team")] });
    const sent = gameWith([...round(5), APPROVED], {
      phase: "mission_vote",
      proposed_team: [],
      legal_actions: [],
      last_team_vote: {
        mission_number: 1,
        proposal_number: 1,
        team: ["p2", "p3"],
        approvals: ["p1", "p2", "p3"],
        rejections: ["p4", "p5"],
        approved: true,
      },
    });
    const view = render(page(voting));
    view.rerender(page(sent));
    advance(CATCH_UP_DELAY_MS);

    expect(screen.getByText("投票通过")).toBeInTheDocument();
    const seats = screen.getByRole("list", { name: "座位" });
    expect(within(seats).getAllByText("赞成")).toHaveLength(3);
    expect(within(seats).getAllByText("反对")).toHaveLength(2);

    advance(2800);
    expect(screen.getByText("队伍出发")).toBeInTheDocument();
  });
});
