import { useEffect, useMemo, useRef, useState } from "react";

import type { Game, LogEntry, Mission, Phase, Speech, TeamVote } from "../../api/client";

/**
 * The server answers one action with everything the bots did after it: a whole
 * round of speeches, a vote, sometimes a mission. Shown at once, the table
 * jumps. So the client replays the public record one step at a time and draws
 * the table as it stood at that step.
 *
 * A step is one public entry, plus two beats the record has no entry for: the
 * moment the talking stops and the vote opens, and the team leaving on its
 * mission.
 */
export type Step =
  | LogEntry
  | { kind: "voting_opens"; version: number; team: string[] }
  | { kind: "team_departs"; version: number; mission: number; team: string[] };

/** The record is append-only, so the steps of an earlier response are a prefix of a later one. */
export function buildSteps(game: Game): Step[] {
  const steps: Step[] = [];
  let team: string[] = [];
  let spoken = 0;

  for (const entry of game.log) {
    steps.push(entry);
    switch (entry.kind) {
      case "team_proposed":
        team = entry.team;
        spoken = 0;
        break;
      case "speech":
        spoken += 1;
        if (spoken === game.players.length) {
          steps.push({ kind: "voting_opens", version: entry.version, team });
        }
        break;
      case "team_vote":
        if (entry.approved) {
          steps.push({
            kind: "team_departs",
            version: entry.version,
            mission: entry.mission,
            team,
          });
        }
        break;
      default:
        break;
    }
  }
  return steps;
}

/** How long a step stays on the table before the next one, in milliseconds. */
export function stepDuration(step: Step): number {
  switch (step.kind) {
    case "mission_started":
      return 1600;
    case "team_proposed":
      return 2000;
    case "speech":
      // Long enough to read: a pass is quick, a full speech gets its time.
      return step.text === "" ? 800 : Math.min(1400 + step.text.length * 55, 5000);
    case "voting_opens":
      return 1300;
    case "team_vote":
      return 2800;
    case "team_departs":
      return 1800;
    case "mission_result":
      return 2800;
    case "assassination_started":
      return 2200;
    case "assassination":
      return 2400;
    case "game_finished":
      return 0;
  }
}

/** A step that follows a pause (your own move, a poll) starts after this short breath. */
export const CATCH_UP_DELAY_MS = 250;

/**
 * The table as it stood after the first `shown` steps: the same shape the
 * server sends, rebuilt from the public record. Nothing can be done from a
 * past position, so it has no legal actions, and it shows no role the final
 * position revealed.
 */
export function sceneAt(game: Game, steps: readonly Step[], shown: number): Game {
  if (shown >= steps.length) {
    return game;
  }

  const bySeat = [...game.players].sort((a, b) => a.seat - b.seat);
  const nextLeader = (id: string | null): string | null => {
    const index = bySeat.findIndex((player) => player.id === id);
    return index < 0 ? id : bySeat[(index + 1) % bySeat.length].id;
  };

  let version = 0;
  let phase: Phase = "lobby";
  let leader: string | null = null;
  let current: number | null = null;
  let proposal: number | null = null;
  let proposed: string[] = [];
  let speeches: Speech[] = [];
  let speaker: string | null = null;
  let lastVote: TeamVote | null = null;
  let assassin: string | null = null;
  let target: string | null = null;
  let winner: Game["winner"] = null;
  let reason: Game["win_reason"] = null;
  const missions: Mission[] = game.missions.map((mission) => ({
    ...mission,
    team: [],
    outcome: null,
    fail_votes: null,
  }));

  for (const step of steps.slice(0, shown)) {
    version = step.version;
    speaker = null;
    switch (step.kind) {
      case "mission_started":
        phase = "team_proposal";
        current = step.mission;
        proposal = 1;
        leader = step.leader;
        break;
      case "team_proposed":
        phase = "discussion";
        leader = step.leader;
        proposal = step.proposal;
        proposed = step.team;
        speeches = [];
        break;
      case "speech":
        speeches = [
          ...speeches,
          { player_id: step.player, text: step.text, suspects: step.suspects },
        ];
        speaker = step.player;
        break;
      case "voting_opens":
        phase = "team_vote";
        break;
      case "team_vote":
        lastVote = {
          mission_number: step.mission,
          proposal_number: step.proposal,
          team: proposed,
          approvals: step.approvals,
          rejections: step.rejections,
          approved: step.approved,
        };
        if (step.approved) {
          phase = "mission_vote";
          missions[step.mission - 1] = { ...missions[step.mission - 1], team: proposed };
        } else {
          phase = "team_proposal";
          proposal = step.proposal + 1;
          leader = nextLeader(leader);
        }
        proposed = [];
        break;
      case "team_departs":
        break;
      case "mission_result":
        missions[step.mission - 1] = {
          ...missions[step.mission - 1],
          outcome: step.outcome,
          fail_votes: step.fail_votes,
        };
        break;
      case "assassination_started":
        phase = "assassination";
        assassin = step.assassin;
        break;
      case "assassination":
        target = step.target;
        break;
      case "game_finished":
        phase = "finished";
        winner = step.winner;
        reason = step.reason;
        break;
    }
  }

  return {
    ...game,
    phase,
    leader_id: leader,
    players: game.players.map((player) => ({
      ...player,
      is_leader: player.id === leader,
      thinking: false,
      role: player.is_you ? player.role : null,
      alignment: player.is_you ? player.alignment : null,
    })),
    missions,
    current_mission_number: current,
    proposal_number: proposal,
    proposed_team: proposed,
    speeches,
    speaker_id: speaker,
    team_voted: [],
    your_team_vote: null,
    last_team_vote: lastVote,
    mission_played: [],
    your_mission_card: null,
    assassin_id: assassin,
    assassination_target_id: target,
    winner,
    win_reason: reason,
    legal_actions: [],
    announcements: game.announcements.filter((item) => item.version <= version),
  };
}

export interface Playback {
  /** The table to draw: a past position while replaying, the real one once caught up. */
  scene: Game;
  /** The step on the table right now, if the game has started. */
  beat: Step | null;
  /** Unique per step, so the view can restart an animation when the step changes. */
  beatIndex: number;
  /** There are steps the player has not been shown yet. */
  playing: boolean;
  /** Show the latest position at once. */
  skip: () => void;
}

/**
 * Replays what happened since the player last looked. A game opened in the
 * middle (a page reload) starts caught up: only what arrives afterwards is
 * replayed.
 */
export function usePlayback(game: Game): Playback {
  const steps = useMemo(() => buildSteps(game), [game]);
  const [cursor, setCursor] = useState(steps.length);
  const shown = Math.min(cursor, steps.length);
  const playing = shown < steps.length;
  // A number, so a poll that brings the same steps again does not restart the timer.
  const duration = shown > 0 && playing ? stepDuration(steps[shown - 1]) : 0;
  const caughtUp = useRef(true);

  useEffect(() => {
    if (!playing) {
      caughtUp.current = true;
      return;
    }
    // The step on the table has had its time if we were waiting when the news came.
    const wait = caughtUp.current ? CATCH_UP_DELAY_MS : duration;
    const timer = window.setTimeout(() => {
      caughtUp.current = false;
      setCursor(shown + 1);
    }, wait);
    return () => window.clearTimeout(timer);
  }, [playing, shown, duration]);

  return {
    scene: sceneAt(game, steps, shown),
    beat: shown > 0 ? steps[shown - 1] : null,
    beatIndex: shown,
    playing,
    skip: () => setCursor(steps.length),
  };
}
