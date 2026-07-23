from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

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


class DeadmanTests(unittest.TestCase):
    def test_publisher_body_contains_only_sanitized_contract(self) -> None:
        body = publish.heartbeat_body(2_000_000_000)
        self.assertIn(publish.HEARTBEAT_MARKER, body)
        self.assertIn('"epoch": 2000000000', body)
        payload = json.loads(body.split("```json", 1)[1].rsplit("```", 1)[0])
        self.assertEqual(set(payload), {"epoch", "schema", "source"})
        self.assertNotIn("runner", body.casefold())

    def test_marker_lookup_and_payload_parse(self) -> None:
        comment = {"id": 11, "body": publish.heartbeat_body(2_000_000_000)}
        found = check.find_marker_comment([comment], check.HEARTBEAT_MARKER)
        payload = check.parse_marker_payload(found, check.HEARTBEAT_MARKER)
        self.assertEqual(payload["epoch"], 2_000_000_000)

    def test_fresh_stale_and_future_heartbeat(self) -> None:
        self.assertEqual(
            check.assess_heartbeat({"epoch": 2_000_000_000}, 2_000_000_060), ("", 60)
        )
        reason, age = check.assess_heartbeat({"epoch": 2_000_000_000}, 2_000_001_201)
        self.assertIn("stale", reason)
        self.assertEqual(age, 1201)
        reason, age = check.assess_heartbeat({"epoch": 2_000_000_400}, 2_000_000_000)
        self.assertIn("future", reason)
        self.assertEqual(age, -400)

    def test_bool_and_non_positive_epochs_are_rejected(self) -> None:
        for epoch in (True, False, 0, -1, "2000000000", 1.5, None):
            with self.subTest(epoch=epoch):
                with self.assertRaises(ValueError):
                    check.assess_heartbeat({"epoch": epoch}, 2_000_000_000)

    def test_state_body_round_trips(self) -> None:
        body = check.state_body("degraded", 2_000_000_000, 1_999_999_999)
        comment = {"id": 22, "body": body}
        payload = check.parse_marker_payload(comment, check.STATE_MARKER)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["last_alert_epoch"], 1_999_999_999)
        json.dumps(payload, sort_keys=True)

    def test_discord_webhook_is_bounded_to_https_discord_endpoint(self) -> None:
        accepted = "https://discord.com/api/webhooks/123456/token-value"
        self.assertEqual(check.validate_discord_webhook(accepted), accepted)
        rejected = (
            "http://discord.com/api/webhooks/123/token",
            "https://example.com/api/webhooks/123/token",
            "file:///tmp/secret",
            "https://discord.com/api/webhooks/not-numeric/token",
            "https://discord.com/api/webhooks/123/token?redirect=example",
            "https://discord.com/api/webhooks/123/token/extra",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    check.validate_discord_webhook(value)


if __name__ == "__main__":
    unittest.main()
