import { useState } from "react";

import type { ActionRequest, Game, LegalAction, Mission, Player } from "../../api/client";
import {
  ALIGNMENT_NAMES,
  FALLBACK_REASONS,
  PHASE_NAMES,
  ROLE_HINTS,
  ROLE_NAMES,
  SEEN_AS_NAMES,
  WIN_REASONS,
} from "./labels";

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
  const { game, error, onLeave } = props;
  const names = new Map(game.players.map((player) => [player.id, player.name]));
  const nameOf = (id: string) => names.get(id) ?? id;
  const me = game.players.find((player) => player.is_you);

  return (
    <main className="page">
      <header className="page__header page__header--row">
        <div>
          <p className="eyebrow">房间 {game.room_code}</p>
          <h1>{PHASE_NAMES[game.phase]}</h1>
        </div>
        <button type="button" className="button button--ghost" onClick={onLeave}>
          离开对局
        </button>
      </header>

      {game.phase === "finished" && <Result game={game} />}

      <section className="card" aria-labelledby="action-title">
        <h2 id="action-title">你的操作</h2>
        <ActionPanel {...props} nameOf={nameOf} />
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

      {game.announcements.length > 0 && <Announcements game={game} />}

      {game.missions.length > 0 && <MissionTrack game={game} />}

      <section className="card" aria-labelledby="players-title">
        <h2 id="players-title">玩家</h2>
        <ul className="players">
          {game.players.map((player) => (
            <PlayerRow key={player.id} player={player} game={game} />
          ))}
        </ul>
      </section>

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

type ActionPanelProps = GamePageProps & { nameOf: (id: string) => string };

function ActionPanel(props: ActionPanelProps) {
  const { game, pending, onAction, onLeave } = props;
  const legal = game.legal_actions[0];

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
    case "vote_team":
      return (
        <div className="actions">
          <p>
            队长提议派出：<strong>{game.proposed_team.map(props.nameOf).join("、")}</strong>
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
        {selectedTeam.length}/{size}）。
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

function MissionTrack({ game }: { game: Game }) {
  const rejected = (game.proposal_number ?? 1) - 1;

  return (
    <section className="card" aria-labelledby="missions-title">
      <h2 id="missions-title">任务</h2>
      <ol className="missions">
        {game.missions.map((mission) => (
          <li
            key={mission.number}
            className={`mission mission--${mission.outcome ?? "open"}`}
            aria-current={
              mission.number === game.current_mission_number && game.phase !== "finished"
                ? "step"
                : undefined
            }
          >
            <span className="mission__number">任务 {mission.number}</span>
            <span className="mission__size">{mission.team_size} 人</span>
            <span className="mission__state">{describeMission(mission, game)}</span>
          </li>
        ))}
      </ol>
      {game.proposal_number !== null && (
        <p className="muted">
          本任务已否决 {rejected}/{game.max_rejected_proposals} 次组队；满{" "}
          {game.max_rejected_proposals} 次邪恶方直接获胜。
        </p>
      )}
    </section>
  );
}

function describeMission(mission: Mission, game: Game): string {
  if (mission.outcome === "success") {
    return `✓ 成功（${mission.fail_votes ?? 0} 张失败）`;
  }
  if (mission.outcome === "fail") {
    return `✗ 失败（${mission.fail_votes ?? 0} 张失败）`;
  }
  const needsTwo = mission.fails_required > 1 ? `需 ${mission.fails_required} 张失败` : "";
  if (mission.number === game.current_mission_number && game.phase !== "finished") {
    return needsTwo ? `进行中 · ${needsTwo}` : "进行中";
  }
  return needsTwo || "未开始";
}

function PlayerRow({ player, game }: { player: Player; game: Game }) {
  const onProposedTeam = game.proposed_team.includes(player.id);
  const mission = game.missions.find((m) => m.number === game.current_mission_number);
  const onMission = game.phase === "mission_vote" && (mission?.team.includes(player.id) ?? false);

  return (
    <li className={`player${player.is_you ? " player--you" : ""}`}>
      <span className="player__name">{player.name}</span>
      <span className="player__badges">
        {player.is_you && <span className="badge badge--you">你</span>}
        {player.agent === "random" && <span className="badge">机器人</span>}
        {player.agent === "llm" && <span className="badge badge--ai">AI</span>}
        {player.thinking && <span className="badge badge--thinking">思考中…</span>}
        {player.last_turn === "fallback" && (
          <span className="badge badge--fallback">
            上一步由机器人代打
            {player.fallback_reason !== null && `：${FALLBACK_REASONS[player.fallback_reason]}`}
          </span>
        )}
        {player.is_leader && game.phase !== "finished" && (
          <span className="badge badge--leader">队长</span>
        )}
        {onProposedTeam && <span className="badge badge--team">提名中</span>}
        {onMission && <span className="badge badge--team">任务中</span>}
        {game.phase === "team_vote" && game.team_voted.includes(player.id) && (
          <span className="badge">已投票</span>
        )}
        {game.phase === "mission_vote" && game.mission_played.includes(player.id) && (
          <span className="badge">已出牌</span>
        )}
        {player.seen_as !== null && (
          <span className="badge badge--known">你知道：{SEEN_AS_NAMES[player.seen_as]}</span>
        )}
        {game.assassination_target_id === player.id && (
          <span className="badge badge--evil">被刺杀</span>
        )}
        {player.role !== null && !player.is_you && (
          <span className={`badge badge--${player.alignment ?? "good"}`}>
            {ROLE_NAMES[player.role]}
          </span>
        )}
        {player.role !== null && player.is_you && game.phase === "finished" && (
          <span className={`badge badge--${player.alignment ?? "good"}`}>
            {ROLE_NAMES[player.role]}
          </span>
        )}
      </span>
    </li>
  );
}
