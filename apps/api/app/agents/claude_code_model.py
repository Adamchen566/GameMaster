"""`ModelClient` backed by the Claude Code command line on this computer.

It answers through the account the person is logged in with, so no API key is
needed. Each turn is one non-interactive run (`claude -p`), which takes many
seconds: far slower than an API call.

What the model reads includes text typed by other players, so the run is given
no tools at all (`--tools ""`), no MCP servers, an empty working directory and
no saved session. The whole prompt goes in on standard input, never on the
command line.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.agents.json_reply import parse_json_object, schema_instructions
from app.agents.model import (
    ModelBadOutput,
    ModelReply,
    ModelTimeout,
    ModelUnavailable,
)

DEFAULT_MODEL = "sonnet"
STATUS_TTL_SECONDS = 60.0

Runner = Callable[[Sequence[str], str, float], tuple[int, str]]
"""`(arguments, standard input, timeout) -> (exit code, standard output)`.

Raises `TimeoutError` when the time runs out and `OSError` when the program cannot be started.
"""


def find_claude() -> str | None:
    """Path of the Claude Code executable, if it is installed."""
    return shutil.which("claude")


def run_process(arguments: Sequence[str], stdin: str, timeout_seconds: float) -> tuple[int, str]:
    # An empty directory of its own: nothing of the person's to read, even by mistake.
    with tempfile.TemporaryDirectory(prefix="avalon-seat-") as directory:
        try:
            done = subprocess.run(
                list(arguments),
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                cwd=directory,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(str(error)) from error
    return done.returncode, done.stdout


class ClaudeCodeModel:
    def __init__(
        self,
        executable: str,
        *,
        model: str = DEFAULT_MODEL,
        run: Runner = run_process,
    ) -> None:
        self._executable = executable
        self._model = model
        self._run = run
        self._status: tuple[float, str | None] | None = None

    def _arguments(self) -> list[str]:
        return [
            self._executable,
            "-p",
            "--output-format",
            "json",
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--model",
            self._model,
        ]

    def complete(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        timeout_seconds: float,
    ) -> ModelReply:
        prompt = f"{system}\n\n{schema_instructions(schema)}\n\n{user}"
        try:
            code, output = self._run(self._arguments(), prompt, timeout_seconds)
        except TimeoutError as error:
            raise ModelTimeout(str(error)) from error
        except OSError as error:
            raise ModelUnavailable(f"could not start Claude Code: {error}") from error

        try:
            result = json.loads(output[output.index("{") :])
        except ValueError as error:
            raise ModelUnavailable(f"Claude Code gave no result (exit {code})") from error
        if not isinstance(result, dict) or result.get("is_error"):
            raise ModelUnavailable(f"Claude Code reported an error (exit {code})")

        structured = result.get("structured_output")
        if isinstance(structured, dict):
            data = structured
        else:
            text = result.get("result")
            if not isinstance(text, str) or not text.strip():
                raise ModelBadOutput("The answer contained no text.")
            data = parse_json_object(text)

        reported = result.get("usage")
        usage: dict[str, Any] = reported if isinstance(reported, dict) else {}
        return ModelReply(
            data=data,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )

    def problem(self) -> str | None:
        """Why this seat cannot play right now, or None. Asked rarely: it starts a process."""
        now = time.monotonic()
        if self._status is not None and now - self._status[0] < STATUS_TTL_SECONDS:
            return self._status[1]
        try:
            code, output = self._run([self._executable, "auth", "status"], "", 20.0)
            logged_in = code == 0 and "not logged in" not in output.lower()
            problem = None if logged_in else "not_logged_in"
        except (TimeoutError, OSError):
            problem = "not_responding"
        self._status = (now, problem)
        return problem
