#!/usr/bin/env python3
"""External GitHub-hosted dead-man check for the sanitized CI heartbeat."""

from __future__ import annotations

import json
import os
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "tgv-trading/tg-ci-deadman")
ISSUE_NUMBER = 2
HEARTBEAT_MARKER = "<!-- tg-ci-heartbeat -->"
STATE_MARKER = "<!-- tg-ci-deadman-state -->"
MAX_HEARTBEAT_AGE_SECONDS = 20 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
REPEAT_ALERT_SECONDS = 6 * 60 * 60


def github_request(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GitHub token missing")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "tg-ci-deadman",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    # The URL origin is fixed to api.github.com; only the repository API path varies.
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        body = response.read()
    return json.loads(body) if body else None


def find_marker_comment(comments: object, marker: str) -> dict[str, Any] | None:
    if not isinstance(comments, list):
        return None
    for item in comments:
        if isinstance(item, dict) and marker in str(item.get("body", "")):
            return item
    return None


def parse_marker_payload(comment: dict[str, Any] | None, marker: str) -> dict[str, Any]:
    if comment is None:
        raise ValueError("marker comment missing")
    body = comment.get("body")
    if not isinstance(body, str) or marker not in body:
        raise ValueError("marker missing from comment body")
    remainder = body.split(marker, 1)[1].strip()
    if remainder.startswith("```json") and remainder.endswith("```"):
        remainder = remainder[len("```json") : -len("```")].strip()
    payload = json.loads(remainder)
    if not isinstance(payload, dict):
        raise ValueError("marker payload must be a JSON object")
    return payload


def assess_heartbeat(payload: dict[str, Any], now: int) -> tuple[str, int]:
    epoch = payload.get("epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= 0:
        raise ValueError("heartbeat epoch invalid")
    age = now - epoch
    if age < -MAX_FUTURE_SKEW_SECONDS:
        return "heartbeat timestamp is in the future", age
    if age > MAX_HEARTBEAT_AGE_SECONDS:
        return f"heartbeat stale by {age} seconds", age
    return "", age


def state_body(status: str, now: int, last_alert_epoch: int) -> str:
    payload = {
        "last_alert_epoch": last_alert_epoch,
        "last_check_epoch": now,
        "schema": "tg_ci_deadman_state_v1",
        "status": status,
    }
    return f"{STATE_MARKER}\n```json\n{json.dumps(payload, sort_keys=True)}\n```"


def validate_discord_webhook(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    path_parts = parsed.path.split("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"discord.com", "discordapp.com"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or len(path_parts) != 5
        or path_parts[1:3] != ["api", "webhooks"]
        or not path_parts[3].isdigit()
        or not path_parts[4]
    ):
        raise ValueError("Discord webhook URL is outside the bounded HTTPS endpoint")
    return value


def send_discord(content: str) -> None:
    webhook = os.environ.get("DEADMAN_DISCORD_WEBHOOK")
    if not webhook:
        raise RuntimeError("Discord webhook secret missing")
    webhook = validate_discord_webhook(webhook)
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"content": content}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "tg-ci-deadman"},
    )
    # validate_discord_webhook constrains this to Discord's HTTPS webhook origin.
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        if response.status not in {200, 204}:
            raise RuntimeError(f"Discord webhook returned HTTP {response.status}")


def update_state(comment_id: int, body: str) -> None:
    github_request(
        f"/repos/{REPOSITORY}/issues/comments/{comment_id}",
        method="PATCH",
        payload={"body": body},
    )


def main() -> int:
    now = int(time.time())
    comments = github_request(
        f"/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}/comments?per_page=100"
    )
    heartbeat_comment = find_marker_comment(comments, HEARTBEAT_MARKER)
    state_comment = find_marker_comment(comments, STATE_MARKER)
    state_comment_id = state_comment.get("id") if state_comment else None
    if isinstance(state_comment_id, bool) or not isinstance(state_comment_id, int):
        raise RuntimeError("dead-man state comment missing")

    try:
        heartbeat = parse_marker_payload(heartbeat_comment, HEARTBEAT_MARKER)
        reason, age = assess_heartbeat(heartbeat, now)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        reason = f"heartbeat invalid: {type(exc).__name__}: {exc}"
        age = -1

    try:
        prior = parse_marker_payload(state_comment, STATE_MARKER)
    except (ValueError, TypeError, json.JSONDecodeError):
        prior = {}
    prior_status = prior.get("status")
    last_alert = prior.get("last_alert_epoch")
    if isinstance(last_alert, bool) or not isinstance(last_alert, int):
        last_alert = 0

    if reason:
        should_alert = (
            prior_status != "degraded"
            or last_alert == 0
            or now - last_alert >= REPEAT_ALERT_SECONDS
        )
        if should_alert:
            send_discord(
                "Terminal Gravity external CI dead-man alert: "
                f"the sanitized self-hosted-CI heartbeat is unhealthy ({reason}). "
                "This alert was generated outside the self-hosted machine."
            )
            last_alert = now
        update_state(state_comment_id, state_body("degraded", now, last_alert))
        print(json.dumps({"status": "degraded", "reason": reason, "age_seconds": age}))
        return 0

    if prior_status == "degraded":
        send_discord(
            "Terminal Gravity external CI dead-man recovery: "
            "the sanitized self-hosted-CI heartbeat is healthy again."
        )
    update_state(state_comment_id, state_body("healthy", now, last_alert))
    print(json.dumps({"status": "healthy", "age_seconds": age}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
