import { useEffect, useRef, useState } from "react";

const STORAGE_KEY = "avalon.readAloud";

export interface Voice {
  pitch: number;
  rate: number;
}

const NARRATOR: Voice = { pitch: 1, rate: 1.05 };

function synth(): SpeechSynthesis | null {
  return typeof window !== "undefined" && "speechSynthesis" in window
    ? window.speechSynthesis
    : null;
}

/** Whether this browser can read text aloud at all. */
export function canReadAloud(): boolean {
  return synth() !== null && typeof SpeechSynthesisUtterance !== "undefined";
}

function stored(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "on";
  } catch {
    return false;
  }
}

/** The read-aloud switch, remembered between visits. */
export function useReadAloudSetting() {
  const [enabled, setEnabled] = useState(() => canReadAloud() && stored());

  function toggle() {
    const next = !enabled;
    setEnabled(next);
    if (!next) {
      synth()?.cancel();
    }
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "on" : "off");
    } catch {
      // A browser that refuses storage still reads aloud for this visit.
    }
  }

  return { available: canReadAloud(), enabled, toggle };
}

/**
 * Reads each new line aloud with the browser's own voices: no key, no network.
 * `line` is spoken when `lineKey` changes after the page was opened; what was
 * already on the table then is not read out.
 */
export function useReadAloud(
  enabled: boolean,
  lineKey: number,
  line: string | null,
  voice: Voice | null,
): void {
  const first = useRef(lineKey);

  useEffect(() => {
    const engine = synth();
    if (!enabled || engine === null || line === null || line === "" || lineKey === first.current) {
      return;
    }
    const utterance = new SpeechSynthesisUtterance(line);
    const chosen = voice ?? NARRATOR;
    utterance.lang = "zh-CN";
    utterance.pitch = chosen.pitch;
    utterance.rate = chosen.rate;
    // One speaker at a time: a new line cuts off whatever was still being read.
    engine.cancel();
    engine.speak(utterance);
    // `line` and `voice` belong to `lineKey`; only a new key is a new line.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, lineKey]);

  useEffect(() => () => synth()?.cancel(), []);
}
