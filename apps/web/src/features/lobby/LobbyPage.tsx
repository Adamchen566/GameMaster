import { useState } from "react";
import type { FormEvent } from "react";

import type {
  AiStyle,
  DriverId,
  DriverStatus,
  GmMode,
  RoomOptions,
  SeatChoice,
  ServerConfig,
} from "../../api/client";
import { DRIVER_NAMES, DRIVER_PROBLEMS } from "../game/labels";
import type { PastGame } from "../../session";
import { ApiStatus } from "./ApiStatus";

const PLAYER_COUNTS = [5, 6, 7, 8, 9, 10, 11, 12];
/** From this many players the house rules apply; the official tables stop at ten. */
const HOUSE_RULES_FROM = 11;
const MAX_NICKNAME_LENGTH = 20;
const MAX_BOT_SEATS = 12;

const STYLES: { value: AiStyle; label: string }[] = [
  { value: "baseline", label: "均衡" },
  { value: "cautious", label: "谨慎" },
  { value: "aggressive", label: "激进" },
];

const GM_MODES: { value: GmMode; label: string; needsModel: boolean }[] = [
  { value: "template", label: "固定播报", needsModel: false },
  { value: "ai", label: "AI 主持", needsModel: true },
  { value: "off", label: "关闭", needsModel: false },
];

/** What the lobby assumes until the server has answered: only what always works. */
export const NO_MODELS: ServerConfig = {
  llm_available: false,
  gm_ai_available: false,
  drivers: [],
  personas: [],
};

interface LobbyPageProps {
  creating: boolean;
  error: string | null;
  /** What this server can do: which models can play a seat, who sits in the bot seats. */
  config?: ServerConfig;
  onCreate: (nickname: string, playerCount: number, options: RoomOptions) => void;
  /** Games played in this browser, newest first, to be replayed. */
  history?: PastGame[];
  onReplay?: (game: PastGame) => void;
}

export function LobbyPage({
  creating,
  error,
  config = NO_MODELS,
  onCreate,
  history = [],
  onReplay = () => undefined,
}: LobbyPageProps) {
  // Kept here, not in the reducer: a failed request must not wipe what was typed.
  const [nickname, setNickname] = useState("");
  const [playerCount, setPlayerCount] = useState(5);
  const [spectate, setSpectate] = useState(false);
  // One choice per possible bot seat; the table uses as many as it has seats.
  const [choices, setChoices] = useState<SeatChoice[]>(() => Array(MAX_BOT_SEATS).fill("bot"));
  const [aiStyle, setAiStyle] = useState<AiStyle>("baseline");
  const [gm, setGm] = useState<GmMode>("template");
  const [touched, setTouched] = useState(false);

  const usable = new Set(
    config.drivers.filter((driver) => driver.available).map((driver) => driver.id),
  );
  const botSeats = spectate ? playerCount : playerCount - 1;
  // A choice the server cannot honour falls back to the built-in bot.
  const seats: SeatChoice[] = choices
    .slice(0, botSeats)
    .map((choice) => (choice === "bot" || usable.has(choice) ? choice : "bot"));
  const modelSeats = seats.filter((choice) => choice !== "bot").length;
  const effectiveGm: GmMode = gm === "ai" && !config.gm_ai_available ? "template" : gm;

  const trimmed = nickname.trim();
  const nicknameError =
    trimmed.length === 0
      ? "请输入昵称。"
      : trimmed.length > MAX_NICKNAME_LENGTH
        ? `昵称最多 ${MAX_NICKNAME_LENGTH} 个字。`
        : null;

  function choose(index: number, choice: SeatChoice) {
    setChoices((current) => current.map((old, seat) => (seat === index ? choice : old)));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    if (nicknameError === null && !creating) {
      onCreate(trimmed, playerCount, { seats, spectate, aiStyle, gm: effectiveGm });
    }
  }

  const showNicknameError = touched && nicknameError !== null;

  return (
    <main className="page page--narrow">
      <header className="page__header">
        <p className="eyebrow">Avalon AI Game Master</p>
        <h1>阿瓦隆 · 单人对局</h1>
        <p className="muted">
          你和若干 AI 同桌，也可以只看它们打。完成三次任务，或让任务失败三次。
        </p>
      </header>

      <form className="card form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="nickname">昵称</label>
          <input
            id="nickname"
            name="nickname"
            type="text"
            autoComplete="nickname"
            value={nickname}
            maxLength={MAX_NICKNAME_LENGTH + 10}
            aria-invalid={showNicknameError}
            aria-describedby={showNicknameError ? "nickname-error" : undefined}
            onChange={(event) => setNickname(event.target.value)}
            onBlur={() => setTouched(true)}
          />
          {showNicknameError && (
            <p className="field__error" id="nickname-error">
              {nicknameError}
            </p>
          )}
        </div>

        <fieldset className="field">
          <legend>人数{spectate ? "" : "（含你自己）"}</legend>
          <div className="choices">
            {PLAYER_COUNTS.map((count) => (
              <label key={count} className="choice">
                <input
                  type="radio"
                  name="player-count"
                  value={count}
                  checked={playerCount === count}
                  onChange={() => setPlayerCount(count)}
                />
                <span>{count} 人</span>
              </label>
            ))}
          </div>
          {playerCount >= HOUSE_RULES_FROM && (
            <p className="muted">
              官方规则只到 10 人。11–12 人用扩展规则：约三分之一是邪恶方（11 人 4 个，12 人 5
              个），每轮队伍多 1 人，后面的任务要 2 张失败牌才算失败。
            </p>
          )}
        </fieldset>

        <fieldset className="field">
          <legend>你的位置</legend>
          <div className="choices">
            <label className="choice">
              <input
                type="radio"
                name="spectate"
                checked={!spectate}
                onChange={() => setSpectate(false)}
              />
              <span>上桌一起玩</span>
            </label>
            <label className="choice">
              <input
                type="radio"
                name="spectate"
                checked={spectate}
                onChange={() => setSpectate(true)}
              />
              <span>观战</span>
            </label>
          </div>
          {spectate && (
            <p className="muted">
              所有座位都由 AI 来打。你能看到每个人的身份和心声，但不参与发言和投票。
            </p>
          )}
        </fieldset>

        <fieldset className="field">
          <legend>入座：每个座位由谁来打</legend>
          <ol className="seating">
            {seats.map((choice, index) => {
              const persona = config.personas[index];
              const name = persona?.name ?? `座位 ${index + 1}`;
              return (
                <li key={index} className="seating__seat">
                  <span
                    className="seating__dot"
                    style={{ background: persona?.color }}
                    aria-hidden="true"
                  />
                  <span className="seating__who">
                    <strong>{name}</strong>
                    {persona !== undefined && <span className="muted">{persona.title}</span>}
                  </span>
                  <select
                    aria-label={`${name} 由谁来打`}
                    value={choice}
                    onChange={(event) => choose(index, event.target.value as SeatChoice)}
                  >
                    <option value="bot">内置机器人</option>
                    {config.drivers.map((driver) => (
                      <option key={driver.id} value={driver.id} disabled={!driver.available}>
                        {DRIVER_NAMES[driver.id]}
                        {driver.available ? "" : "（不可用）"}
                      </option>
                    ))}
                  </select>
                </li>
              );
            })}
          </ol>
          {config.drivers.length > 0 ? (
            <ul className="drivers" aria-label="模型状态">
              {config.drivers.map((driver) => (
                <DriverLine key={driver.id} driver={driver} />
              ))}
            </ul>
          ) : (
            <p className="muted">这台服务器没有配置模型，所有座位都是内置机器人。</p>
          )}
          {modelSeats > 0 && (
            <p className="muted">
              {costNote(seats)}
            </p>
          )}
        </fieldset>

        {modelSeats > 0 && (
          <fieldset className="field">
            <legend>AI 玩家的打法</legend>
            <div className="choices">
              {STYLES.map((style) => (
                <label key={style.value} className="choice">
                  <input
                    type="radio"
                    name="ai-style"
                    value={style.value}
                    checked={aiStyle === style.value}
                    onChange={() => setAiStyle(style.value)}
                  />
                  <span>{style.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        )}

        <fieldset className="field">
          <legend>主持人</legend>
          <div className="choices">
            {GM_MODES.filter((mode) => config.gm_ai_available || !mode.needsModel).map((mode) => (
              <label key={mode.value} className="choice">
                <input
                  type="radio"
                  name="gm"
                  value={mode.value}
                  checked={effectiveGm === mode.value}
                  onChange={() => setGm(mode.value)}
                />
                <span>{mode.label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {error !== null && (
          <p className="alert alert--danger" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="button button--primary" disabled={creating}>
          {creating ? "正在创建…" : spectate ? "创建并观战" : "创建对局"}
        </button>
      </form>

      {history.length > 0 && (
        <section className="card" aria-labelledby="history-title">
          <h2 id="history-title">最近的对局</h2>
          <p className="muted">记在这个浏览器里。结束的对局可以从头回放，看到每一步的身份、心声和模型的原始回答。</p>
          <ol className="history">
            {history.map((game) => (
              <li key={game.gameId} className="history__game">
                <span>
                  <strong>{game.playerCount} 人局</strong>
                  {game.spectate ? " · 观战" : ` · ${game.nickname}`}
                  <span className="muted"> · {formatWhen(game.createdAt)}</span>
                </span>
                <button
                  type="button"
                  className="button button--ghost"
                  aria-label={`回放 ${formatWhen(game.createdAt)} 的 ${game.playerCount} 人局`}
                  onClick={() => onReplay(game)}
                >
                  回放
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      <ApiStatus />
    </main>
  );
}

function DriverLine({ driver }: { driver: DriverStatus }) {
  const problem = driver.problem === null ? null : (DRIVER_PROBLEMS[driver.problem] ?? driver.problem);
  return (
    <li className={`drivers__line${driver.available && problem === null ? " drivers__line--ok" : ""}`}>
      <strong>{DRIVER_NAMES[driver.id]}</strong>
      <span>{problem ?? "可用"}</span>
    </li>
  );
}

/** What the chosen seats will cost, in the terms of whoever pays for it. */
function costNote(seats: SeatChoice[]): string {
  const used = new Set(seats.filter((choice): choice is DriverId => choice !== "bot"));
  const parts: string[] = [];
  if (used.has("claude") || used.has("deepseek")) {
    parts.push("用 API 的座位每个回合调用一次模型，按量计费");
  }
  if (used.has("claude_code")) {
    parts.push("本机 Claude Code 的座位用你自己的订阅额度，每步要十几秒到一两分钟");
  }
  if (used.has("codex")) {
    parts.push("本机 Codex 的座位用你的 ChatGPT 额度，每步几秒到半分钟");
  }
  return `${parts.join("；")}。`;
}

function formatWhen(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) {
    return "时间未知";
  }
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${when.getMonth() + 1}月${when.getDate()}日 ${pad(when.getHours())}:${pad(when.getMinutes())}`;
}
