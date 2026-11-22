import { useState } from "react";
import type { FormEvent } from "react";

import { ApiStatus } from "./ApiStatus";

const PLAYER_COUNTS = [5, 6, 7, 8, 9, 10];
const MAX_NICKNAME_LENGTH = 20;

interface LobbyPageProps {
  creating: boolean;
  error: string | null;
  onCreate: (nickname: string, playerCount: number) => void;
}

export function LobbyPage({ creating, error, onCreate }: LobbyPageProps) {
  // Kept here, not in the reducer: a failed request must not wipe what was typed.
  const [nickname, setNickname] = useState("");
  const [playerCount, setPlayerCount] = useState(5);
  const [touched, setTouched] = useState(false);

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
      onCreate(trimmed, playerCount);
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
