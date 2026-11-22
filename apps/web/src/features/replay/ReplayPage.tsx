import { useEffect, useMemo, useState } from "react";

import type { DriverId, FallbackReason, Replay, Turn } from "../../api/client";
import {
  describeStep,
  PhaseTrack,
  Result,
  RoundTable,
  SpeechLog,
  Thoughts,
} from "../game/GamePage";
import { DRIVER_BADGES, FALLBACK_REASONS, PHASE_NAMES } from "../game/labels";
import { buildSteps, sceneAt, stepDuration } from "../game/playback";
import type { Playback, Step } from "../game/playback";

export const SPEEDS = [0.5, 1, 2, 4] as const;

interface ReplayPageProps {
  replay: Replay;
  onLeave: () => void;
}

/**
 * A finished game, played back from the deal. Every role is shown from the
 * start, the AI seats' thoughts appear at the moment they had them, and under
 * the table are the model turns behind the step on show: what the model was
 * given and every answer it sent back.
 */
export function ReplayPage({ replay, onLeave }: ReplayPageProps) {
  const { turns } = replay;
  // Nobody is "you" in a replay: every seat shows its role on the table from the start.
  const final = useMemo(
    () => ({
      ...replay.game,
      players: replay.game.players.map((player) => ({ ...player, is_you: false })),
    }),
    [replay.game],
  );
  const steps = useMemo(() => buildSteps(final), [final]);
  const [shown, setShown] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<number>(1);
  const atEnd = shown >= steps.length;

  useEffect(() => {
    if (!playing || atEnd) {
      return;
    }
    // The first step comes at once; each later one after the time the last one needs.
    const wait = shown === 0 ? 300 : stepDuration(steps[shown - 1]) / speed;
    const timer = window.setTimeout(() => setShown(shown + 1), wait);
    return () => window.clearTimeout(timer);
  }, [playing, atEnd, shown, speed, steps]);

  const beat = shown > 0 ? steps[shown - 1] : null;
  const scene = sceneAt(final, steps, shown, true);
  const playback: Playback = {
    scene,
    beat,
    beatIndex: shown,
    playing: !atEnd,
    skip: () => setShown(steps.length),
  };
  const names = new Map(final.players.map((player) => [player.id, player.name]));
  const nameOf = (id: string) => names.get(id) ?? id;
  const upTo = beat?.version ?? 0;
  const thoughts = final.thoughts.filter((thought) => atEnd || thought.version <= upTo);
  const behind = turnsBehind(steps, shown, turns);
  const line = beat === null ? null : describeStep(beat, scene, nameOf);

  function go(to: number) {
    setPlaying(false);
    setShown(Math.max(0, Math.min(steps.length, to)));
  }

  return (
    <main className="page page--table">
      <header className="page__header page__header--row">
        <div>
          <p className="eyebrow">
            回放 · 房间 {final.room_code} · {final.players.length} 人局
            {final.ruleset_id === "extended" && " · 扩展规则"}
          </p>
          <h1>{line?.title ?? PHASE_NAMES[scene.phase]}</h1>
          <PhaseTrack phase={scene.phase} />
        </div>
        <div className="page__tools">
          <button type="button" className="button button--ghost" onClick={onLeave}>
            回到大厅
          </button>
        </div>
      </header>

      <section className="card replay" aria-label="回放控制">
        <div className="replay__buttons">
          <button type="button" className="button button--ghost" onClick={() => go(0)}>
            回到开头
          </button>
          <button
            type="button"
            className="button button--ghost"
            disabled={shown === 0}
            onClick={() => go(shown - 1)}
          >
            上一步
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => {
              if (atEnd) {
                setShown(0);
                setPlaying(true);
              } else {
                setPlaying(!playing);
              }
            }}
          >
            {atEnd ? "重新播放" : playing ? "暂停" : "播放"}
          </button>
          <button
            type="button"
            className="button button--ghost"
            disabled={atEnd}
            onClick={() => go(shown + 1)}
          >
            下一步
          </button>
          <button type="button" className="button button--ghost" onClick={() => go(steps.length)}>
            跳到结局
          </button>
          <label className="replay__speed">
            <span>速度</span>
            <select
              aria-label="播放速度"
              value={speed}
              onChange={(event) => setSpeed(Number(event.target.value))}
            >
              {SPEEDS.map((value) => (
                <option key={value} value={value}>
                  {value}×
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="replay__scrub">
          <input
            type="range"
            aria-label="回放进度"
            min={0}
            max={steps.length}
            value={shown}
            onChange={(event) => go(Number(event.target.value))}
          />
          <span className="muted">
            第 {shown}/{steps.length} 步
          </span>
        </label>
      </section>

      <RoundTable game={scene} nameOf={nameOf} playback={playback} />

      {atEnd && <Result game={final} />}

      <div className="below-table">
        <ModelTurns turns={behind} nameOf={nameOf} step={beat} />
        <Totals turns={turns} />
      </div>

      {scene.speeches.length > 0 && <SpeechLog game={scene} nameOf={nameOf} />}

      {thoughts.length > 0 && <Thoughts thoughts={thoughts} nameOf={nameOf} finished />}
    </main>
  );
}

/**
 * The model turns that led to the step on show: those after the previous
 * step's events, up to and including this step's. A turn is filed under the
 * version of the first event its action produced, so a vote's hidden ballots
 * land on the step that reveals them.
 */
export function turnsBehind(steps: readonly Step[], shown: number, turns: readonly Turn[]): Turn[] {
  if (shown === 0) {
    return [];
  }
  const to = steps[shown - 1].version;
  const from = shown > 1 ? steps[shown - 2].version : 0;
  return turns.filter((turn) => turn.version > from && turn.version <= to);
}

function ModelTurns({
  turns,
  nameOf,
  step,
}: {
  turns: Turn[];
  nameOf: (id: string) => string;
  step: Step | null;
}) {
  return (
    <section className="card" aria-labelledby="turns-title">
      <h2 id="turns-title">这一步背后的模型回合</h2>
      {turns.length === 0 ? (
        <p className="muted">
          {step === null
            ? "开始播放后，这里会列出每一步里模型看到了什么、回答了什么。"
            : "这一步没有模型参与：由内置机器人或规则自动推进。"}
        </p>
      ) : (
        <ol className="turns">
          {turns.map((turn) => (
            <li key={`${turn.version}:${turn.player_id}`} className="turn">
              <p className="turn__head">
                <strong>{nameOf(turn.player_id)}</strong>
                <span className="badge badge--ai">
                  {DRIVER_BADGES[turn.driver as DriverId] ?? "AI"}
                </span>
                {turn.source === "fallback" ? (
                  <span className="badge badge--fallback">
                    机器人代打
                    {turn.fallback_reason !== null &&
                      `：${FALLBACK_REASONS[turn.fallback_reason as FallbackReason] ?? turn.fallback_reason}`}
                  </span>
                ) : (
                  <span className="badge badge--good">模型作答</span>
                )}
                <span className="muted">
                  {(turn.duration_ms / 1000).toFixed(1)} 秒 · {turn.attempts} 次调用 ·{" "}
                  {turn.input_tokens + turn.output_tokens} tokens
                </span>
              </p>
              {turn.exchanges.map((exchange, index) => (
                <div key={index} className="turn__exchange">
                  {exchange.answer !== undefined && <Answer answer={exchange.answer} />}
                  {exchange.rejected !== undefined && (
                    <p className="turn__rejected">规则拒绝了这次回答：{exchange.rejected}</p>
                  )}
                  {exchange.error !== undefined && (
                    <p className="turn__rejected">
                      调用失败：{exchange.error}
                      {exchange.detail !== undefined && `（${exchange.detail}）`}
                    </p>
                  )}
                </div>
              ))}
              {turn.observation !== null && (
                <details className="turn__raw">
                  <summary>模型看到的全部内容</summary>
                  <pre>{JSON.stringify(turn.observation, null, 2)}</pre>
                </details>
              )}
              {turn.exchanges.length > 0 && (
                <details className="turn__raw">
                  <summary>原始回答</summary>
                  <pre>{JSON.stringify(turn.exchanges, null, 2)}</pre>
                </details>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

const ACTION_NAMES: Record<string, string> = {
  propose_team: "提名队伍",
  speak: "发言",
  vote_team: "组队投票",
  vote_mission: "出任务牌",
  assassinate: "刺杀",
};

/** The part of an answer a person wants to read; the rest is under "原始回答". */
function Answer({ answer }: { answer: Record<string, unknown> }) {
  const text = (key: string) => (typeof answer[key] === "string" ? (answer[key] as string) : "");
  const action = text("action");
  let decision = ACTION_NAMES[action] ?? action;
  if (action === "vote_team") {
    decision += answer.approve === true ? "：赞成" : "：反对";
  } else if (action === "vote_mission") {
    decision += answer.success === true ? "：成功" : "：失败";
  }
  return (
    <dl className="answer">
      <dt>决定</dt>
      <dd>{decision}</dd>
      {text("speech") !== "" && (
        <>
          <dt>说出口的</dt>
          <dd>{text("speech")}</dd>
        </>
      )}
      {text("inner") !== "" && (
        <>
          <dt>心里想的</dt>
          <dd>{text("inner")}</dd>
        </>
      )}
      {text("note") !== "" && (
        <>
          <dt>给自己的笔记</dt>
          <dd>{text("note")}</dd>
        </>
      )}
    </dl>
  );
}

/** What the whole game took from each model. */
function Totals({ turns }: { turns: Turn[] }) {
  const byDriver = new Map<string, Turn[]>();
  for (const turn of turns) {
    byDriver.set(turn.driver, [...(byDriver.get(turn.driver) ?? []), turn]);
  }
  return (
    <section className="card" aria-labelledby="totals-title">
      <h2 id="totals-title">整局模型统计</h2>
      {turns.length === 0 ? (
        <p className="muted">这一局没有模型座位，全部由内置机器人完成。</p>
      ) : (
        <table className="totals">
          <thead>
            <tr>
              <th scope="col">模型</th>
              <th scope="col">回合</th>
              <th scope="col">代打</th>
              <th scope="col">平均耗时</th>
              <th scope="col">tokens</th>
            </tr>
          </thead>
          <tbody>
            {[...byDriver].map(([driver, group]) => {
              const fallbacks = group.filter((turn) => turn.source === "fallback").length;
              const seconds = group.reduce((sum, turn) => sum + turn.duration_ms, 0) / group.length / 1000;
              const tokens = group.reduce(
                (sum, turn) => sum + turn.input_tokens + turn.output_tokens,
                0,
              );
              return (
                <tr key={driver}>
                  <th scope="row">{DRIVER_BADGES[driver as DriverId] ?? driver}</th>
                  <td>{group.length}</td>
                  <td>{fallbacks}</td>
                  <td>{seconds.toFixed(1)} 秒</td>
                  <td>{tokens.toLocaleString("zh-CN")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
