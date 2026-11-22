"""`ModelClient` backed by the OpenAI Codex command line on this computer.

It answers through the ChatGPT account the person is logged in with, so no API
key is needed and the turns come out of that subscription. Each turn is one
non-interactive run (`codex exec`), a few seconds to half a minute.

What the model reads includes text typed by other players, so each run:

- switches off the shell and every other tool Codex could reach for,
- runs in the read-only sandbox, in an empty directory of its own,
- ignores the person's own Codex config and rules (no MCP servers, no plugins),
- saves no session, and
- takes the prompt on standard input, never on the command line.

The answer is held to the decision schema (`--output-schema`) and read back
from the file Codex writes its last message to.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from app.agents.json_reply import parse_json_object, schema_instructions
from app.agents.model import (
    ModelReply,
    ModelTimeout,
    ModelUnavailable,
)

STATUS_TTL_SECONDS = 60.0

DISABLED_FEATURES = (
    "shell_tool",
    "apps",
    "browser_use",
    "computer_use",
    "image_generation",
    "multi_agent",
    "plugins",
    "hooks",
)
"""Everything that would let a run act outside its answer."""

Runner = Callable[[Sequence[str], str, float], tuple[int, str]]
"""`(arguments, standard input, timeout) -> (exit code, combined output)`.

Raises `TimeoutError` when the time runs out and `OSError` when the program cannot be started.
"""


def find_codex() -> str | None:
    """Path of the Codex executable: on PATH, or the newest one the desktop app installed."""
    found = shutil.which("codex")
    if found is not None:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    installed = sorted(
        Path(local, "OpenAI", "Codex", "bin").glob("*/codex.exe"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return str(installed[0]) if installed else None


def run_process(arguments: Sequence[str], stdin: str, timeout_seconds: float) -> tuple[int, str]:
    try:
        done = subprocess.run(
            list(arguments),
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(str(error)) from error
    return done.returncode, done.stdout + done.stderr


class CodexModel:
    def __init__(
        self, executable: str, *, model: str | None = None, run: Runner = run_process
    ) -> None:
        self._executable = executable
        self._model = model
        self._run = run
        self._status: tuple[float, str | None] | None = None

    def _arguments(self, directory: Path) -> list[str]:
        arguments = [
            self._executable,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--cd",
            str(directory),
            "--color",
            "never",
            "--output-schema",
            str(directory / "schema.json"),
            "--output-last-message",
            str(directory / "answer.json"),
        ]
        for feature in DISABLED_FEATURES:
            arguments += ["--disable", feature]
        if self._model:
            arguments += ["--model", self._model]
        # The prompt comes from standard input.
        return [*arguments, "-"]

    def complete(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        timeout_seconds: float,
    ) -> ModelReply:
        prompt = f"{system}\n\n{schema_instructions(schema)}\n\n{user}"
        with tempfile.TemporaryDirectory(prefix="avalon-seat-") as name:
            directory = Path(name)
            (directory / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
            try:
                code, output = self._run(self._arguments(directory), prompt, timeout_seconds)
            except TimeoutError as error:
                raise ModelTimeout(str(error)) from error
            except OSError as error:
                raise ModelUnavailable(f"could not start Codex: {error}") from error
            answer = directory / "answer.json"
            text = answer.read_text(encoding="utf-8") if answer.exists() else ""

        if not text.strip():
            # Codex prints why on failure (not logged in, usage limit, network); keep it short.
            last = output.strip().splitlines()[-1][:120] if output.strip() else ""
            raise ModelUnavailable(f"Codex gave no answer (exit {code}): {last}")
        return ModelReply(
            data=parse_json_object(text),
            input_tokens=0,
            output_tokens=_tokens_used(output),
        )

    def problem(self) -> str | None:
        """Why this seat cannot play right now, or None. Asked rarely: it starts a process."""
        now = time.monotonic()
        if self._status is not None and now - self._status[0] < STATUS_TTL_SECONDS:
            return self._status[1]
        try:
            code, output = self._run([self._executable, "login", "status"], "", 20.0)
            logged_in = code == 0 and "not logged in" not in output.lower()
            problem = None if logged_in else "codex_not_logged_in"
        except (TimeoutError, OSError):
            problem = "not_responding"
        self._status = (now, problem)
        return problem


def _tokens_used(output: str) -> int:
    """Codex reports one total after `tokens used`; it is counted as output, a rough guide only."""
    lines = output.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.strip() == "tokens used":
            digits = "".join(ch for ch in lines[index + 1] if ch.isdigit())
            return int(digits) if digits else 0
    return 0
