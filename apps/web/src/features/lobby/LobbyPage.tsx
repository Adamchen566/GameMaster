import { useState } from "react";
import type { FormEvent } from "react";

import type { AiStyle, GmMode, RoomOptions } from "../../api/client";
import { ApiStatus } from "./ApiStatus";

const PLAYER_COUNTS = [5, 6, 7, 8, 9, 10];
const MAX_NICKNAME_LENGTH = 20;

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

interface LobbyPageProps {
  creating: boolean;
  error: string | null;
  /** Whether the server can run model-driven seats and the AI game master. */
  llmAvailable?: boolean;
  onCreate: (nickname: string, playerCount: number, options: RoomOptions) => void;
}

export function LobbyPage({ creating, error, llmAvailable = false, onCreate }: LobbyPageProps) {
  // Kept here, not in the reducer: a failed request must not wipe what was typed.
  const [nickname, setNickname] = useState("");
  const [playerCount, setPlayerCount] = useState(5);
  const [aiSeats, setAiSeats] = useState(0);
  const [aiStyle, setAiStyle] = useState<AiStyle>("baseline");
  const [gm, setGm] = useState<GmMode>("template");
  const [touched, setTouched] = useState(false);

  const botSeats = playerCount - 1;
  // Choices that need a model fall back to what the server can do.
  const effectiveAiSeats = llmAvailable ? Math.min(aiSeats, botSeats) : 0;
  const effectiveGm: GmMode = gm === "ai" && !llmAvailable ? "template" : gm;

  const trimmed = nickname.trim();
  const nicknameError =
    trimmed.length === 0
      ? "请输入昵称。"
      : trimmed.length > MAX_NICKNAME_LENGTH
        ? `昵称最多 ${MAX_NICKNAME_LENGTH} 个字。`
        : null;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    if (nicknameError === null && !creating) {
      onCreate(trimmed, playerCount, { aiSeats: effectiveAiSeats, aiStyle, gm: effectiveGm });
    }
  }

  const showNicknameError = touched && nicknameError !== null;

  return (
    <main className="page page--narrow">
      <header className="page__header">
        <p className="eyebrow">Avalon AI Game Master</p>
        <h1>阿瓦隆 · 单人对局</h1>
        <p className="muted">你和若干机器人同桌。完成三次任务，或让任务失败三次。</p>
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
          <legend>人数（含你自己）</legend>
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
        </fieldset>

        {llmAvailable ? (
          <>
            <fieldset className="field">
              <legend>AI 玩家席位（其余席位是随机机器人）</legend>
              <div className="choices">
                {Array.from({ length: botSeats + 1 }, (_, count) => (
                  <label key={count} className="choice">
                    <input
                      type="radio"
                      name="ai-seats"
                      value={count}
                      checked={effectiveAiSeats === count}
                      onChange={() => setAiSeats(count)}
                    />
                    <span>{count} 个</span>
                  </label>
                ))}
              </div>
              <p className="muted">AI 玩家的每个回合都会调用一次模型，会产生费用。</p>
            </fieldset>

            {effectiveAiSeats > 0 && (
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
          </>
        ) : (
          <p className="muted">这台服务器没有配置模型，其余席位都是随机机器人。</p>
        )}

        <fieldset className="field">
          <legend>主持人</legend>
          <div className="choices">
            {GM_MODES.filter((mode) => llmAvailable || !mode.needsModel).map((mode) => (
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
          {creating ? "正在创建…" : "创建对局"}
        </button>
      </form>

      <ApiStatus />
    </main>
  );
}
