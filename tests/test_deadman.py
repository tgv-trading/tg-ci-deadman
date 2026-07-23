from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = load("check_heartbeat", "scripts/check-heartbeat.py")
publish = load("publish_heartbeat", "scripts/publish-heartbeat.py")


def heartbeat_payload(epoch: int) -> dict[str, object]:
    return {
        "epoch": epoch,
        "schema": check.HEARTBEAT_SCHEMA,
        "source": check.HEARTBEAT_SOURCE,
    }


def heartbeat_comment(epoch: int) -> dict[str, object]:
    return {
        "id": check.HEARTBEAT_COMMENT_ID,
        "issue_url": (
            f"https://api.github.com/repos/{check.REPOSITORY}/issues/"
            f"{check.ISSUE_NUMBER}"
        ),
        "user": {"login": check.HEARTBEAT_COMMENT_AUTHOR},
        "body": publish.heartbeat_body(epoch),
    }


PROBE_NONCE = "a" * 64


def healthy_watchdog_state(
    started_at: int = 100, completed_at: int = 100, nonce: str = PROBE_NONCE
) -> dict[str, object]:
    return {
        "probe_attestation": {
            "completed_at": completed_at,
            "nonce": nonce,
            "schema": publish.PROBE_ATTESTATION_SCHEMA,
            "source": publish.PROBE_ATTESTATION_SOURCE,
            "started_at": started_at,
            "status": "healthy",
        }
    }


class DeadmanTests(unittest.TestCase):
    def test_publisher_body_contains_only_sanitized_contract(self) -> None:
        body = publish.heartbeat_body(2_000_000_000)
        self.assertIn(publish.HEARTBEAT_MARKER, body)
        payload = json.loads(body.split("```json", 1)[1].rsplit("```", 1)[0])
        self.assertEqual(set(payload), check.HEARTBEAT_KEYS)
        self.assertEqual(payload["schema"], check.HEARTBEAT_SCHEMA)
        self.assertEqual(payload["source"], check.HEARTBEAT_SOURCE)
        self.assertNotIn("runner", body.casefold())

    def test_exact_heartbeat_comment_identity_and_payload(self) -> None:
        payload = check.validate_heartbeat_comment(heartbeat_comment(2_000_000_000))
        self.assertEqual(payload["epoch"], 2_000_000_000)
        for field, value in (
            ("id", 999),
            ("issue_url", "https://api.github.com/repos/example/other/issues/2"),
            ("user", {"login": "someone-else"}),
        ):
            with self.subTest(field=field):
                candidate = heartbeat_comment(2_000_000_000)
                candidate[field] = value
                with self.assertRaises(ValueError):
                    check.validate_heartbeat_comment(candidate)

    def test_fresh_stale_and_future_heartbeat(self) -> None:
        self.assertEqual(
            check.assess_heartbeat(heartbeat_payload(2_000_000_000), 2_000_000_060),
            ("", 60),
        )
        reason, age = check.assess_heartbeat(
            heartbeat_payload(2_000_000_000), 2_000_001_201
        )
        self.assertIn("stale", reason)
        self.assertEqual(age, 1201)
        reason, age = check.assess_heartbeat(
            heartbeat_payload(2_000_000_400), 2_000_000_000
        )
        self.assertIn("future", reason)
        self.assertEqual(age, -400)

    def test_malformed_heartbeat_contracts_are_rejected(self) -> None:
        malformed = (
            {"epoch": 2_000_000_000},
            {**heartbeat_payload(2_000_000_000), "private": "data"},
            {**heartbeat_payload(2_000_000_000), "schema": "wrong"},
            {**heartbeat_payload(2_000_000_000), "source": "wrong"},
        )
        for payload in malformed:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    check.assess_heartbeat(payload, 2_000_000_060)
        for epoch in (True, False, 0, -1, "2000000000", 1.5, None):
            with self.subTest(epoch=epoch):
                payload = heartbeat_payload(2_000_000_000)
                payload["epoch"] = epoch
                with self.assertRaises(ValueError):
                    check.assess_heartbeat(payload, 2_000_000_000)

    def test_current_watchdog_state_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            valid = healthy_watchdog_state()
            state.write_text(json.dumps(valid), encoding="utf-8")
            publish.require_current_healthy_state(
                state,
                expected_nonce=PROBE_NONCE,
                probe_started_at=100,
                now=101,
            )
            attestation = valid["probe_attestation"]
            self.assertIsInstance(attestation, dict)
            attestation_dict = (
                dict(attestation) if isinstance(attestation, dict) else {}
            )
            invalid = (
                healthy_watchdog_state(completed_at=99),
                healthy_watchdog_state(completed_at=200),
                healthy_watchdog_state(nonce="b" * 64),
                {"probe_attestation": {**attestation_dict, "extra": True}},
            )
            for candidate in invalid:
                state.write_text(json.dumps(candidate), encoding="utf-8")
                with self.subTest(candidate=candidate):
                    with self.assertRaises(RuntimeError):
                        publish.require_current_healthy_state(
                            state,
                            expected_nonce=PROBE_NONCE,
                            probe_started_at=100,
                            now=101,
                        )

    def test_stale_same_second_watchdog_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(
                json.dumps(healthy_watchdog_state(nonce="b" * 64)), encoding="utf-8"
            )
            with self.assertRaises(RuntimeError):
                publish.require_current_healthy_state(
                    state,
                    expected_nonce=PROBE_NONCE,
                    probe_started_at=100,
                    now=100,
                )

    def test_publisher_always_runs_watchdog_into_selected_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            watchdog = Path(directory) / "watchdog.py"
            calls: list[list[str]] = []

            def fake_run(argv: list[str]) -> str:
                calls.append(argv)
                if argv[0] == "python3":
                    nonce = argv[argv.index("--probe-nonce") + 1]
                    state.write_text(
                        json.dumps(healthy_watchdog_state(nonce=nonce)),
                        encoding="utf-8",
                    )
                return ""

            with (
                mock.patch.object(publish, "run_command", side_effect=fake_run),
                mock.patch.object(publish.time, "time", side_effect=[100, 101]),
            ):
                publish.publish(watchdog, state)
            self.assertEqual(
                calls[0][:4], ["python3", str(watchdog), "--state", str(state)]
            )
            self.assertEqual(calls[0][4], "--probe-nonce")
            self.assertRegex(calls[0][5], r"^[a-f0-9]{64}$")
            self.assertIn(str(publish.HEARTBEAT_COMMENT_ID), calls[1][4])

    def test_cli_has_no_watchdog_bypass(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            [
                "publish-heartbeat",
                "--watchdog",
                "watch.py",
                "--local-state",
                "state.json",
            ],
        ):
            args = publish.parse_args()
        self.assertFalse(hasattr(args, "skip_watchdog"))
        self.assertEqual(args.watchdog, Path("watch.py"))

    def test_state_contract_rejects_future_or_malformed_alert_time(self) -> None:
        now = 2_000_000_000
        valid = {
            "last_alert_epoch": now - 10,
            "last_check_epoch": now,
            "schema": check.STATE_SCHEMA,
            "status": "degraded",
        }
        self.assertEqual(check.normalize_state(valid, now), valid)
        malformed = (
            {**valid, "last_alert_epoch": now + 1},
            {**valid, "last_alert_epoch": now + 1, "last_check_epoch": now + 1},
            {**valid, "last_alert_epoch": -1},
            {**valid, "last_check_epoch": now + check.MAX_FUTURE_SKEW_SECONDS + 1},
            {**valid, "schema": "wrong"},
            {**valid, "extra": True},
        )
        for payload in malformed:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    check.normalize_state(payload, now)

    def test_invalid_state_causes_integrity_alert_and_failed_check(self) -> None:
        with (
            mock.patch.object(check.time, "time", return_value=2_000_000_100),
            mock.patch.object(
                check,
                "github_request",
                return_value=heartbeat_comment(2_000_000_000),
            ),
            mock.patch.object(check, "load_discord_state", side_effect=ValueError),
            mock.patch.object(check, "send_discord") as send,
            mock.patch.object(check, "update_discord_state") as update,
            mock.patch("builtins.print"),
        ):
            self.assertEqual(check.main(), 1)
        send.assert_called_once()
        self.assertIn("integrity alert", send.call_args.args[0])
        update.assert_called_once()

    def test_discord_state_message_id_is_numeric(self) -> None:
        with mock.patch.dict(os.environ, {"DEADMAN_STATE_MESSAGE_ID": "123456"}):
            self.assertEqual(check.state_message_id(), "123456")
        for value in ("", "not-numeric", "123/456", "１２３", "١٢٣"):
            with self.subTest(value=value):
                with mock.patch.dict(
                    os.environ, {"DEADMAN_STATE_MESSAGE_ID": value}, clear=False
                ):
                    with self.assertRaises(RuntimeError):
                        check.state_message_id()

    def test_discord_webhook_and_redirect_policy_are_fail_closed(self) -> None:
        accepted = (
            "https://discord.com/api/webhooks/123456/"
            "abcdefghijklmnopqrstuvwxyz_ABCD-123456"
        )
        self.assertEqual(check.validate_discord_webhook(accepted), accepted)
        rejected = (
            "http://discord.com/api/webhooks/123/token",
            "https://example.com/api/webhooks/123/token",
            "file:///tmp/secret",
            "https://discord.com/api/webhooks/not-numeric/token",
            "https://discord.com/api/webhooks/１２３/abcdefghijklmnopqrstuvwxyz_ABCD-123456",
            "https://discord.com/api/webhooks/123/..",
            "https://discord.com/api/webhooks/123/%2F",
            "https://discord.com/api/webhooks/123/short-token",
            "https://discord.com/api/webhooks/123/token?redirect=example",
            "https://discord.com/api/webhooks/123/token/extra",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    check.validate_discord_webhook(value)
        handler = check.NoRedirectHandler()
        self.assertIsNone(
            handler.redirect_request(
                mock.Mock(),
                mock.Mock(),
                302,
                "Found",
                mock.Mock(),
                "http://127.0.0.1/internal",
            )
        )

    def test_secret_workflow_cannot_run_pull_request_head_code(self) -> None:
        workflow = (ROOT / ".github/workflows/external-deadman.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request", workflow)
        self.assertIn("repository_dispatch:", workflow)
        self.assertIn("types: [ci-deadman-manual]", workflow)
        self.assertIn("if: github.ref == 'refs/heads/main'", workflow)


if __name__ == "__main__":
    unittest.main()
