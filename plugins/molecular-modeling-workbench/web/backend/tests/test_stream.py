"""T2.5: SSE progress/log stream and offset-based reconnect resume."""

from __future__ import annotations

import json
import unittest

from web.backend.tests import helpers


def parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event: dict = {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event["event"] = line[len("event: ") :]
            elif line.startswith("data: "):
                event.setdefault("data", []).append(line[len("data: ") :])
            elif line.startswith("id: "):
                event["id"] = line[len("id: ") :]
        events.append(event)
    return events


class StreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.tmp, self.workspace = helpers.make_client()
        self.log = self.workspace / "md.log"
        self.initial = "Step 1000\nremaining wall clock time: 2h\n5.5 ns/day\n"
        self.log.write_text(self.initial, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _stream(self, offset: int | None = None):
        headers = helpers.auth_headers()
        if offset is not None:
            headers["Last-Event-ID"] = str(offset)
        return self.client.get(
            f"/stream/log?log={self.log}&total_steps=10000", headers=headers
        )

    def test_progress_event_matches_parse_log(self) -> None:
        resp = self._stream()
        self.assertEqual(resp.status_code, 200, resp.text)
        events = parse_sse(resp.text)
        progress = next(e for e in events if e["event"] == "progress")
        data = json.loads(progress["data"][0])
        self.assertEqual(data["source"], "monitoring")
        self.assertEqual(data["step"], 1000)
        self.assertEqual(data["eta"], "2h")
        self.assertAlmostEqual(data["percent"], 10.0)

    def test_reconnect_resumes_without_duplicate_or_loss(self) -> None:
        first = self._stream()
        events = parse_sse(first.text)
        log_event = next(e for e in events if e["event"] == "log")
        offset = int(log_event["id"])
        self.assertEqual(offset, len(self.initial.encode("utf-8")))

        appended = "Step 2000\n6.0 ns/day\n"
        with self.log.open("a", encoding="utf-8") as handle:
            handle.write(appended)

        second = self._stream(offset=offset)
        events2 = parse_sse(second.text)
        log_event2 = next(e for e in events2 if e["event"] == "log")
        data2 = "\n".join(log_event2["data"])
        self.assertNotIn("Step 1000", data2)
        self.assertIn("Step 2000", data2)
        self.assertEqual(int(log_event2["id"]), offset + len(appended.encode("utf-8")))

    def test_log_outside_workspace_rejected(self) -> None:
        outside = self.tmp.name + "/secret.log"
        resp = self.client.get(
            f"/stream/log?log={outside}&total_steps=10000",
            headers=helpers.auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
