#!/usr/bin/env python3
"""Publish a sanitized heartbeat after the local CI watchdog reports healthy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
from typing import Any

REPOSITORY = "tgv-trading/tg-ci-deadman"
ISSUE_NUMBER = 2
HEARTBEAT_MARKER = "<!-- tg-ci-heartbeat -->"
DEFAULT_WATCHDOG = Path(
    "/srv/gateways/terminal-gravity/scripts/tg-github-runner-watchdog.py"
)
DEFAULT_LOCAL_STATE = Path(
    "/srv/gateways/terminal-gravity/state/tg-github-runner-watchdog.json"
)


def heartbeat_body(now: int) -> str:
    payload = {
        "epoch": now,
        "schema": "tg_ci_deadman_v1",
        "source": "self_hosted_ci_health",
    }
    return f"{HEARTBEAT_MARKER}\n```json\n{json.dumps(payload, sort_keys=True)}\n```"


def find_marker_comment(comments: object, marker: str) -> dict[str, Any] | None:
    if not isinstance(comments, list):
        return None
    for item in comments:
        if isinstance(item, dict) and marker in str(item.get("body", "")):
            return item
    return None


def require_healthy_state(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "healthy":
        raise RuntimeError("local CI watchdog is not healthy; heartbeat withheld")


def run_command(argv: list[str]) -> str:
    completed = subprocess.run(
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


def publish(now: int, watchdog: Path, local_state: Path, skip_watchdog: bool) -> None:
    if not skip_watchdog:
        run_command(["python3", str(watchdog)])
    require_healthy_state(local_state)
    comments = json.loads(
        run_command(
            [
                "gh",
                "api",
                f"repos/{REPOSITORY}/issues/{ISSUE_NUMBER}/comments?per_page=100",
            ]
        )
    )
    comment = find_marker_comment(comments, HEARTBEAT_MARKER)
    comment_id = comment.get("id") if comment else None
    if isinstance(comment_id, bool) or not isinstance(comment_id, int):
        raise RuntimeError("heartbeat marker comment missing")
    run_command(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{REPOSITORY}/issues/comments/{comment_id}",
            "-f",
            f"body={heartbeat_body(now)}",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watchdog", type=Path, default=DEFAULT_WATCHDOG)
    parser.add_argument("--local-state", type=Path, default=DEFAULT_LOCAL_STATE)
    parser.add_argument("--now", type=int)
    parser.add_argument("--skip-watchdog", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = args.now if args.now is not None else int(time.time())
    publish(now, args.watchdog, args.local_state, args.skip_watchdog)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
