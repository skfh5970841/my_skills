"""Shell-free external command execution with explicit failure semantics."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


COMPLETED = "completed"
BLOCKED_EXTERNAL = "blocked_external"


@dataclass(frozen=True)
class RunConfig:
    command: tuple[str, ...]
    cwd: Path
    timeout_seconds: int
    stdin_text: str
    model: str
    reasoning: str
    runtime: str
    expect_json: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.command, tuple) or not self.command or not all(
            isinstance(part, str) and part for part in self.command
        ):
            raise ValueError("command must be a non-empty tuple of non-empty strings")
        if not isinstance(self.cwd, Path):
            raise TypeError("cwd must be a Path")
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive integer")
        if not isinstance(self.stdin_text, str):
            raise TypeError("stdin_text must be a string")
        for field_name in ("model", "reasoning", "runtime"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.expect_json, bool):
            raise TypeError("expect_json must be boolean")


@dataclass(frozen=True)
class RunResult:
    status: str
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_ms: int


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def run_command(config: RunConfig) -> RunResult:
    """Run one argv command and return auditable output instead of raising externally."""
    if not isinstance(config, RunConfig):
        raise TypeError("config must be a RunConfig")

    started = time.monotonic()
    try:
        completed = subprocess.run(
            config.command,
            cwd=config.cwd,
            input=config.stdin_text,
            text=True,
            capture_output=True,
            timeout=config.timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        return RunResult(
            BLOCKED_EXTERNAL,
            None,
            _text(error.stdout),
            _text(error.stderr),
            _elapsed_ms(started),
        )
    except OSError as error:
        return RunResult(
            BLOCKED_EXTERNAL,
            None,
            "",
            str(error),
            _elapsed_ms(started),
        )

    stdout = _text(completed.stdout)
    stderr = _text(completed.stderr)
    status = COMPLETED
    if completed.returncode != 0 or not stdout.strip():
        status = BLOCKED_EXTERNAL
    elif config.expect_json:
        try:
            json.loads(stdout, parse_constant=_reject_json_constant)
        except (TypeError, ValueError, json.JSONDecodeError):
            status = BLOCKED_EXTERNAL

    return RunResult(
        status,
        completed.returncode,
        stdout,
        stderr,
        _elapsed_ms(started),
    )
