import { useState } from "react";
import type { CSSProperties } from "react";

import type { ActionRequest, Game, LegalAction, Mission, Phase, Player } from "../../api/client";
import {
  ALIGNMENT_NAMES,
  FALLBACK_REASONS,
  PHASE_NAMES,
  ROLE_HINTS,
  ROLE_NAMES,
  SEEN_AS_NAMES,
  WIN_REASONS,
} from "./labels";
import { usePlayback } from "./playback";
import type { Playback, Step } from "./playback";

const SPEECH_LIMIT = 200;
const MAX_SUSPECTS = 3;

interface GamePageProps {
  game: Game;
  pending: boolean;
  error: string | null;
  selectedTeam: string[];
  onToggleTeam: (playerId: string) => void;
  onAction: (action: ActionRequest) => void;
  onLeave: () => void;
}

export function GamePage(props: GamePageProps) {
  const { error, onLeave } = props;
  // What is drawn is the table at the step being replayed, not always the latest position.
  const playback = usePlayback(props.game);
  const game = playback.scene;
  const names = new Map(game.players.map((player) => [player.id, player.name]));
  const nameOf = (id: string) => names.get(id) ?? id;
  const me = game.players.find((player) => player.is_you);

  return (
    <main className="page page--table">
      <header className="page__header page__header--row">
        <div>
          <p className="eyebrow">房间 {game.room_code}</p>
          <h1>{PHASE_NAMES[game.phase]}</h1>
          <PhaseTrack phase={game.phase} />
        </div>
        <button type="button" className="button button--ghost" onClick={onLeave}>
          离开对局
        </button>
      </header>

      <RoundTable game={game} nameOf={nameOf} playback={playback} />

      {/* Below the table, so the table itself never moves when the game ends. */}
      {game.phase === "finished" && <Result game={game} />}

      <div className="below-table">
        <section className="card" aria-labelledby="action-title">
          <h2 id="action-title">你的操作</h2>
          <ActionPanel {...props} game={game} nameOf={nameOf} playback={playback} />
          {error !== null && (
            <p className="alert alert--danger" role="alert">
              {error}
            </p>
          )}
        </section>

        {me?.role != null && game.phase !== "finished" && (
          <section className="card card--secret" aria-labelledby="role-title">
            <h2 id="role-title">你的身份</h2>
            <p className="role">
              <strong>{ROLE_NAMES[me.role]}</strong>
              {me.alignment !== null && (
                <span className={`badge badge--${me.alignment}`}>
                  {ALIGNMENT_NAMES[me.alignment]}
                </span>
              )}
            </p>
            <p className="muted">{ROLE_HINTS[me.role]}</p>
          </section>
        )}
      </div>

      {game.speeches.length > 0 && <SpeechLog game={game} nameOf={nameOf} />}

      {game.announcements.length > 0 && <Announcements game={game} />}

      {game.last_team_vote !== null && (
        <section className="card" aria-labelledby="vote-title">
          <h2 id="vote-title">
            上一次组队投票：{game.last_team_vote.approved ? "通过" : "否决"}
          </h2>
          <p className="muted">
            任务 {game.last_team_vote.mission_number} 第 {game.last_team_vote.proposal_number}{" "}
            次提案，队伍：{game.last_team_vote.team.map(nameOf).join("、")}
          </p>
          <p>赞成：{game.last_team_vote.approvals.map(nameOf).join("、") || "无"}</p>
          <p>反对：{game.last_team_vote.rejections.map(nameOf).join("、") || "无"}</p>
        </section>
      )}
    </main>
  );
}

function Result({ game }: { game: Game }) {
  if (game.winner === null || game.win_reason === null) {
    return null;
  }
  return (
    <section className={`card result result--${game.winner}`} aria-labelledby="result-title">
      <h2 id="result-title">{ALIGNMENT_NAMES[game.winner]}获胜</h2>
      <p>{WIN_REASONS[game.win_reason]}。</p>
    </section>
  );
}

// --- The table ---------------------------------------------------------------

/**
 * Where a seat sits on the oval, in percent of the table's box. Your own seat
 * is at the bottom; the others follow clockwise in seat order, which is also
 * the order in which the leader token and the right to speak travel.
 */
export function seatPosition(offset: number, count: number): { left: number; top: number } {
  const angle = Math.PI / 2 + (2 * Math.PI * offset) / count;
  return { left: 50 + 43 * Math.cos(angle), top: 50 + 41 * Math.sin(angle) };
}

function RoundTable({
  game,
  nameOf,
  playback,
}: {
  game: Game;
  nameOf: (id: string) => string;
  playback: Playback;
}) {
  const count = game.players.length;
  const mySeat = game.players.find((player) => player.is_you)?.seat ?? 0;
  const speeches = new Map(game.speeches.map((speech) => [speech.player_id, speech]));

  return (
    <div className="table">
      <section className="table__centre" aria-labelledby="missions-title">
        <h2 id="missions-title">任务</h2>
        <ol className="missions">
          {game.missions.map((mission) => (
            <MissionCard key={mission.number} mission={mission} game={game} />
          ))}
        </ol>
        {game.missions.length === 0 && <p className="muted">开始后，五张任务卡会摆在这里。</p>}
        {game.proposal_number !== null && (
          <p className="table__track">
            本任务已否决 {game.proposal_number - 1}/{game.max_rejected_proposals} 次组队；满{" "}
            {game.max_rejected_proposals} 次邪恶方直接获胜。
          </p>
        )}
        {game.proposed_team.length > 0 && (
          <p className="table__proposal">
            提名队伍：<strong>{game.proposed_team.map(nameOf).join("、")}</strong>
          </p>
        )}
        <Stage game={game} nameOf={nameOf} playback={playback} />
      </section>

      <ul className="table__seats" aria-label="座位">
        {game.players.map((player) => {
          const position = seatPosition((player.seat - mySeat + count) % count, count);
          const style: CSSProperties = { left: `${position.left}%`, top: `${position.top}%` };
          return (
            <SeatCard
              key={player.id}
              player={player}
              game={game}
              speech={speeches.get(player.id)?.text}
              beat={playback.beat}
              style={style}
            />
          );
        })}
      </ul>
    </div>
  );
}

const TRACK: { phase: Phase; name: string }[] = [
  { phase: "team_proposal", name: "组队" },
  { phase: "discussion", name: "发言" },
  { phase: "team_vote", name: "投票" },
  { phase: "mission_vote", name: "任务" },
];

/** Where the round is: every mission goes through the same four stages. */
function PhaseTrack({ phase }: { phase: Phase }) {
  if (!TRACK.some((stage) => stage.phase === phase)) {
    return null;
  }
  return (
    <ol className="track" aria-label="本轮进度">
      {TRACK.map((stage) => (
        <li
          key={stage.phase}
          className="track__stage"
          aria-current={stage.phase === phase ? "step" : undefined}
        >
          {stage.name}
        </li>
      ))}
    </ol>
  );
}

interface Line {
  title: string;
  body: string;
  tone: "neutral" | "good" | "evil";
}

function describeStep(step: Step, game: Game, nameOf: (id: string) => string): Line {
  const names = (ids: string[]) => ids.map(nameOf).join("、");
  switch (step.kind) {
    case "mission_started":
      return {
        title: `任务 ${step.mission} 开始`,
        body: `队长是 ${nameOf(step.leader)}，由队长挑选队伍。`,
        tone: "neutral",
      };
    case "team_proposed":
      return {
        title: `${nameOf(step.leader)} 提名了队伍`,
        body: `${names(step.team)}。从队长开始，每人说一次。`,
        tone: "neutral",
      };
    case "speech": {
      const suspects = step.suspects.length > 0 ? `（点名怀疑：${names(step.suspects)}）` : "";
      return {
        title: `${nameOf(step.player)} 发言`,
        body: `${step.text === "" ? "过。" : step.text}${suspects}`,
        tone: "neutral",
      };
    }
    case "voting_opens":
      return {
        title: "发言结束，开始投票",
        body: `是否派出 ${names(step.team)}？`,
        tone: "neutral",
      };
    case "team_vote":
      return {
        title: step.approved ? "投票通过" : "投票否决",
        body: `赞成 ${step.approvals.length} 票，反对 ${step.rejections.length} 票。${
          step.approved ? "" : "队长顺时针移交给下一位。"
        }`,
        tone: step.approved ? "good" : "evil",
      };
    case "team_departs":
      return {
        title: "队伍出发",
        body: `${names(step.team)} 正在执行任务 ${step.mission}，各自暗中出牌。`,
        tone: "neutral",
      };
    case "mission_result":
      return {
        title: `任务 ${step.mission} ${step.outcome === "success" ? "成功" : "失败"}`,
        body: `翻出 ${step.fail_votes} 张失败牌。`,
        tone: step.outcome === "success" ? "good" : "evil",
      };
    case "assassination_started":
      return {
        title: "正义方完成了三次任务",
        body: "刺客还有最后一次机会：找出梅林。",
        tone: "evil",
      };
    case "assassination":
      return {
        title: "刺客出手",
        body: `指认 ${nameOf(step.target)} 是梅林。`,
        tone: "evil",
      };
    case "game_finished":
      return {
        title: `${ALIGNMENT_NAMES[step.winner]}获胜`,
        body: `${WIN_REASONS[step.reason]}。`,
        tone: step.winner,
      };
  }
}

/** The one thing happening at the table right now, in the middle of it. */
function Stage({
  game,
  nameOf,
  playback,
}: {
  game: Game;
  nameOf: (id: string) => string;
  playback: Playback;
}) {
  const line = playback.beat === null ? null : describeStep(playback.beat, game, nameOf);

  return (
    <div className="stage" aria-live="polite">
      {line !== null && (
        // Keyed by step so each one arrives with its own entrance.
        <p key={playback.beatIndex} className={`stage__line stage__line--${line.tone}`}>
          <strong>{line.title}</strong>
          <span>{line.body}</span>
        </p>
      )}
    </div>
  );
}

function MissionCard({ mission, game }: { mission: Mission; game: Game }) {
  const current = mission.number === game.current_mission_number && game.phase !== "finished";
  const state = mission.outcome === "success" ? "成功" : mission.outcome === "fail" ? "失败" : "未做";

  return (
    <li
      className={`mission mission--${mission.outcome ?? "open"}`}
      aria-current={current ? "step" : undefined}
    >
      <span className="mission__number">任务 {mission.number}</span>
      <span className="mission__state">{state}</span>
      <span className="mission__detail">{missionDetail(mission, current)}</span>
    </li>
  );
}

function missionDetail(mission: Mission, current: boolean): string {
  if (mission.outcome !== null) {
    return `${mission.fail_votes ?? 0} 张失败牌`;
  }
  const size = `${mission.team_size} 人`;
  const needsTwo = mission.fails_required > 1 ? ` · 需 ${mission.fails_required} 张失败` : "";
  return current ? `进行中 · ${size}${needsTwo}` : `${size}${needsTwo}`;
}

function SeatCard({
  player,
  game,
  speech,
  beat,
  style,
}: {
  player: Player;
  game: Game;
  speech: string | undefined;
  beat: Step | null;
  style: CSSProperties;
}) {
  const playing = game.phase !== "finished";
  const mission = game.missions.find((m) => m.number === game.current_mission_number);
  const onProposedTeam = game.proposed_team.includes(player.id);
  const onMission = game.phase === "mission_vote" && (mission?.team.includes(player.id) ?? false);
  const speaking = game.speaker_id === player.id;
  const lastVote = game.last_team_vote;
  // The moment the ballots are turned over, and while the team sets off.
  const counting = beat?.kind === "team_vote" || beat?.kind === "team_departs";
  // After that only while the table is choosing the next team: later it is old news.
  const showLastVote = lastVote !== null && (counting || game.phase === "team_proposal");
  const voteWord = counting ? "" : "上轮";
  const classes = [
    "seat",
    player.is_you ? "seat--you" : "",
    speaking ? "seat--speaking" : "",
    onProposedTeam || onMission ? "seat--on-team" : "",
  ];

  return (
    <li className={classes.filter(Boolean).join(" ")} style={style}>
      {speech !== undefined && (
        // The full text is in the speech list below; this is the picture of it.
        <p className="seat__speech" aria-hidden="true" title={speech}>
          {speech === "" ? "（过）" : speech}
        </p>
      )}
      <span className="seat__name">{player.name}</span>
      <span className="seat__badges">
        {player.is_you && <span className="badge badge--you">你</span>}
        {player.agent === "random" && <span className="badge">机器人</span>}
        {player.agent === "llm" && <span className="badge badge--ai">AI</span>}
        {player.is_leader && playing && <span className="badge badge--leader">队长</span>}
        {speaking && <span className="badge badge--speaking">发言中</span>}
        {player.thinking && <span className="badge badge--thinking">思考中…</span>}
        {player.last_turn === "fallback" && (
          <span className="badge badge--fallback">
            上一步由机器人代打
            {player.fallback_reason !== null && `：${FALLBACK_REASONS[player.fallback_reason]}`}
          </span>
        )}
        {onProposedTeam && <span className="badge badge--team">提名中</span>}
        {onMission && <span className="badge badge--team">任务中</span>}
        {game.phase === "team_vote" && game.team_voted.includes(player.id) && (
          <span className="badge">已投票</span>
        )}
        {game.phase === "mission_vote" && game.mission_played.includes(player.id) && (
          <span className="badge">已出牌</span>
        )}
        {showLastVote && lastVote.approvals.includes(player.id) && (
          <span className="badge badge--good">{voteWord}赞成</span>
        )}
        {showLastVote && lastVote.rejections.includes(player.id) && (
          <span className="badge badge--evil">{voteWord}反对</span>
        )}
        {player.seen_as !== null && (
          <span className="badge badge--known">你知道：{SEEN_AS_NAMES[player.seen_as]}</span>
        )}
        {game.assassination_target_id === player.id && (
          <span className="badge badge--evil">被刺杀</span>
        )}
        {player.role !== null && (!player.is_you || !playing) && (
          <span className={`badge badge--${player.alignment ?? "good"}`}>
            {ROLE_NAMES[player.role]}
          </span>
        )}
      </span>
    </li>
  );
}

function SpeechLog({ game, nameOf }: { game: Game; nameOf: (id: string) => string }) {
  return (
    <section className="card" aria-labelledby="speech-title">
      <h2 id="speech-title">本轮发言</h2>
      <ol className="speeches">
        {game.speeches.map((speech) => (
          <li key={speech.player_id} className="speech">
            <span className="speech__who">{nameOf(speech.player_id)}</span>
            <span className="speech__text">{speech.text === "" ? "（过）" : speech.text}</span>
            {speech.suspects.length > 0 && (
              <span className="speech__suspects">
                点名怀疑：{speech.suspects.map(nameOf).join("、")}
              </span>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

// --- What you can do ---------------------------------------------------------

type ActionPanelProps = GamePageProps & { nameOf: (id: string) => string; playback: Playback };

function ActionPanel(props: ActionPanelProps) {
  const { game, pending, onAction, onLeave, playback } = props;
  const legal = game.legal_actions[0];

  if (playback.playing) {
    return (
      <div className="actions">
        <p className="muted" role="status">
          桌上正在进行，轮到你时这里会出现操作。
        </p>
        <button type="button" className="button button--ghost" onClick={playback.skip}>
          跳过，直接看现在
        </button>
      </div>
    );
  }
  if (game.phase === "finished") {
    return (
      <div className="actions">
        <p>这一局结束了，所有身份已公开。</p>
        <button type="button" className="button button--primary" onClick={onLeave}>
          再来一局
        </button>
      </div>
    );
  }
  if (legal === undefined) {
    const thinking = game.players.filter((player) => player.thinking);
    return (
      <p className="muted" role="status">
        {thinking.length > 0
          ? `等待 ${thinking.map((player) => player.name).join("、")} 行动…`
          : "等待其他玩家行动…"}
      </p>
    );
  }

  switch (legal.type) {
    case "start_game":
      return (
        <div className="actions">
          <p>所有席位已就座。开始后会随机发身份并选出第一任队长。</p>
          <button
            type="button"
            className="button button--primary"
            disabled={pending}
            onClick={() => onAction({ type: "start_game" })}
          >
            开始游戏
          </button>
        </div>
      );
    case "propose_team":
      return <ProposeTeam {...props} legal={legal} />;
    case "speak":
      // Keyed by version so the draft is cleared for the next round of speeches.
      return <Speak key={game.version} {...props} legal={legal} />;
    case "vote_team":
      return (
        <div className="actions">
          <p>
            大家都说完了。队长提议派出：
            <strong>{game.proposed_team.map(props.nameOf).join("、")}</strong>
            。你同意吗？
          </p>
          <div className="actions__row">
            <button
              type="button"
              className="button button--primary"
              disabled={pending}
              onClick={() => onAction({ type: "vote_team", approve: true })}
            >
              赞成
            </button>
            <button
              type="button"
              className="button button--secondary"
              disabled={pending}
              onClick={() => onAction({ type: "vote_team", approve: false })}
            >
              反对
            </button>
          </div>
        </div>
      );
    case "vote_mission":
      return (
        <div className="actions">
          <p>
            你在任务队伍里。
            {legal.can_fail ? "你可以让任务成功或失败。" : "正义方只能出成功牌。"}
          </p>
          <div className="actions__row">
            <button
              type="button"
              className="button button--primary"
              disabled={pending}
              onClick={() => onAction({ type: "vote_mission", success: true })}
            >
              任务成功
            </button>
            {legal.can_fail && (
              <button
                type="button"
                className="button button--danger"
                disabled={pending}
                onClick={() => onAction({ type: "vote_mission", success: false })}
              >
                任务失败
              </button>
            )}
          </div>
        </div>
      );
    case "assassinate":
      return <Assassinate {...props} legal={legal} />;
  }
}

function ProposeTeam({
  game,
  pending,
  selectedTeam,
  onToggleTeam,
  onAction,
  nameOf,
  legal,
}: ActionPanelProps & { legal: LegalAction }) {
  const size = legal.team_size ?? 0;
  const complete = selectedTeam.length === size;

  return (
    <div className="actions">
      <p>
        你是队长。为任务 {game.current_mission_number} 选出 <strong>{size}</strong> 人（已选{" "}
        {selectedTeam.length}/{size}）。提交后由你第一个发言。
      </p>
      <div className="choices" role="group" aria-label="选择任务成员">
        {legal.targets.map((id) => {
          const selected = selectedTeam.includes(id);
          return (
            <button
              key={id}
              type="button"
              className={`chip${selected ? " chip--selected" : ""}`}
              aria-pressed={selected}
              disabled={pending || (!selected && complete)}
              onClick={() => onToggleTeam(id)}
            >
              {nameOf(id)}
            </button>
          );
        })}
      </div>
      <button
        type="button"
        className="button button--primary"
        disabled={pending || !complete}
        onClick={() => onAction({ type: "propose_team", team: selectedTeam })}
      >
        提交队伍
      </button>
    </div>
  );
}

function Speak({
  game,
  pending,
  onAction,
  nameOf,
  legal,
}: ActionPanelProps & { legal: LegalAction }) {
  const [text, setText] = useState("");
  const [suspects, setSuspects] = useState<string[]>([]);
  const isLeader = game.leader_id === game.you_id;
  const tooLong = text.trim().length > SPEECH_LIMIT;

  function toggle(id: string) {
    setSuspects((current) =>
      current.includes(id) ? current.filter((other) => other !== id) : [...current, id],
    );
  }

  return (
    <div className="actions">
      <p>
        轮到你发言。
        {isLeader ? "说说你为什么选这支队伍。" : "说说你对这支队伍的看法，其他人会据此判断。"}
      </p>
      <div className="field">
        <label htmlFor="speech">你的发言</label>
        <textarea
          id="speech"
          rows={3}
          value={text}
          aria-invalid={tooLong}
          aria-describedby="speech-count"
          placeholder="例如：这队我不放心，上一轮失败时其中一人在队里。"
          onChange={(event) => setText(event.target.value)}
        />
        <p id="speech-count" className={tooLong ? "field__error" : "muted"}>
          {text.trim().length}/{SPEECH_LIMIT} 字
        </p>
      </div>
      <div className="choices" role="group" aria-label="点名怀疑（最多 3 人）">
        {legal.targets.map((id) => {
          const selected = suspects.includes(id);
          return (
            <button
              key={id}
              type="button"
              className={`chip${selected ? " chip--selected" : ""}`}
              aria-pressed={selected}
              disabled={pending || (!selected && suspects.length >= MAX_SUSPECTS)}
              onClick={() => toggle(id)}
            >
              {nameOf(id)}
            </button>
          );
        })}
      </div>
      <p className="muted">点名是公开的：机器人会把被点名当成一条线索。</p>
      <div className="actions__row">
        <button
          type="button"
          className="button button--primary"
          disabled={pending || tooLong || (text.trim() === "" && suspects.length === 0)}
          onClick={() => onAction({ type: "speak", text: text.trim(), suspects })}
        >
          发言
        </button>
        <button
          type="button"
          className="button button--secondary"
          disabled={pending}
          onClick={() => onAction({ type: "speak", text: "", suspects: [] })}
        >
          过
        </button>
      </div>
    </div>
  );
}

function Assassinate({
  pending,
  onAction,
  nameOf,
  legal,
}: ActionPanelProps & { legal: LegalAction }) {
  const [targetId, setTargetId] = useState<string | null>(null);

  return (
    <div className="actions">
      <p>正义方赢下了三次任务。你是刺客：指认谁是梅林？猜中则邪恶方获胜。</p>
      <div className="choices" role="radiogroup" aria-label="选择刺杀目标">
        {legal.targets.map((id) => (
          <button
            key={id}
            type="button"
            role="radio"
            className={`chip${targetId === id ? " chip--selected" : ""}`}
            aria-checked={targetId === id}
            disabled={pending}
            onClick={() => setTargetId(id)}
          >
            {nameOf(id)}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="button button--primary"
        disabled={pending || targetId === null}
        onClick={() => targetId !== null && onAction({ type: "assassinate", target_id: targetId })}
      >
        确认刺杀
      </button>
    </div>
  );
}

const ANNOUNCEMENTS_SHOWN = 5;

function Announcements({ game }: { game: Game }) {
  // Newest first; the server sends them oldest first.
  const latest = game.announcements.slice(-ANNOUNCEMENTS_SHOWN).reverse();

  return (
    <section className="card" aria-labelledby="gm-title">
      <h2 id="gm-title">主持人</h2>
      <ol className="announcements">
        {latest.map((item, index) => (
          <li
            key={item.version}
            className={`announcement announcement--${item.tone}`}
            aria-current={index === 0 ? "true" : undefined}
          >
            <p>{item.announcement}</p>
            {/* A model's line is colour; the fact it decorates is always shown too. */}
            {item.source === "model" && <p className="muted">{item.facts}</p>}
            {index === 0 && item.rule_hint !== "" && (
              <p className="announcement__hint">规则提示：{item.rule_hint}</p>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
