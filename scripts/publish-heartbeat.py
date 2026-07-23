#!/usr/bin/env python3
"""Publish a sanitized heartbeat after a current local CI watchdog probe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Fixed executable names and shell=False keep subprocess scope bounded.
import subprocess  # nosec B404
import time
from typing import cast

REPOSITORY = "tgv-trading/tg-ci-deadman"
HEARTBEAT_COMMENT_ID = 5_055_931_210
HEARTBEAT_MARKER = "<!-- tg-ci-heartbeat -->"
MAX_LOCAL_FUTURE_SKEW_SECONDS = 5


def heartbeat_body(now: int) -> str:
    payload = {
        "epoch": now,
        "schema": "tg_ci_deadman_v1",
        "source": "self_hosted_ci_health",
    }
    return f"{HEARTBEAT_MARKER}\n```json\n{json.dumps(payload, sort_keys=True)}\n```"


def require_current_healthy_state(
    path: Path, *, probe_started_at: int, now: int
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "healthy":
        raise RuntimeError("local CI watchdog is not healthy; heartbeat withheld")

    started = payload.get("last_probe_started_at")
    completed = payload.get("last_probe_completed_at")
    healthy = payload.get("last_healthy_at")
    epochs = (started, completed, healthy)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in epochs):
        raise RuntimeError("local CI watchdog state timestamps are invalid")
    started_epoch = cast(int, started)
    completed_epoch = cast(int, completed)
    healthy_epoch = cast(int, healthy)
    if not (
        probe_started_at <= started_epoch <= completed_epoch <= healthy_epoch
        and completed_epoch <= now + MAX_LOCAL_FUTURE_SKEW_SECONDS
    ):
        raise RuntimeError("local CI watchdog state is not from the current probe")


def run_command(argv: list[str]) -> str:
    # argv is locally constructed and is never interpreted by a shell.
    completed = subprocess.run(  # nosec B603
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().replace("\n", " ")
        raise RuntimeError(
            f"command_failed:{argv[0]}:{completed.returncode}:{detail[:240]}"
        )
    return completed.stdout


def publish(watchdog: Path, local_state: Path) -> None:
    probe_started_at = int(time.time())
    run_command(["python3", str(watchdog), "--state", str(local_state)])
    now = int(time.time())
    require_current_healthy_state(
        local_state, probe_started_at=probe_started_at, now=now
    )
    run_command(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{REPOSITORY}/issues/comments/{HEARTBEAT_COMMENT_ID}",
            "-f",
            f"body={heartbeat_body(now)}",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watchdog", type=Path, required=True)
    parser.add_argument("--local-state", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    publish(args.watchdog, args.local_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
