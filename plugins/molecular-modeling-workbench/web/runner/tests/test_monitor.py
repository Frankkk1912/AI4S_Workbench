"""T1.6: live monitoring collection (parse_log reuse, ETA unknown, stale)."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from web.runner import monitor


class MonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.log = self.root / "md.log"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_log(self, text: str, mtime: float | None = None) -> None:
        self.log.write_text(text, encoding="utf-8")
        if mtime is not None:
            import os

            os.utime(self.log, (mtime, mtime))

    def test_collect_matches_parse_log_and_labels_monitoring(self) -> None:
        self._write_log("Step 1000\nremaining wall clock time: 2h\n5.5 ns/day\n")
        data = monitor.collect_progress(self.log, total_steps=10000)
        self.assertEqual(data["source"], "monitoring")
        self.assertEqual(data["step"], 1000)
        self.assertAlmostEqual(data["percent"], 10.0)
        self.assertEqual(data["ns_per_day"], 5.5)
        self.assertEqual(data["eta"], "2h")
        self.assertFalse(data["stale"])

    def test_missing_eta_is_unavailable_not_zero(self) -> None:
        self._write_log("Step 100\n3.1 ns/day\n")
        data = monitor.collect_progress(self.log, total_steps=10000)
        self.assertEqual(data["source"], "monitoring")
        self.assertEqual(data["eta"], "unavailable")
        self.assertNotEqual(data["eta"], 0)

    def test_stale_tracks_mtime(self) -> None:
        self._write_log("Step 100\n")
        data = monitor.collect_progress(
            self.log, total_steps=10000, stale_minutes=1 / 60
        )
        self.assertFalse(data["stale"])
        # age the log by > stale_minutes
        aged = time.time() - 120
        self._write_log("Step 100\n", mtime=aged)
        data = monitor.collect_progress(
            self.log, total_steps=10000, stale_minutes=1 / 60
        )
        self.assertTrue(data["stale"])

    def test_read_log_tail_returns_text_and_next_offset(self) -> None:
        self._write_log("line one\nline two\n")
        text, offset = monitor.read_log_tail(self.log, 0)
        self.assertIn("line one", text)
        self.assertIn("line two", text)
        self.assertEqual(offset, len(text.encode("utf-8")))
        # second read from offset yields nothing new
        text2, offset2 = monitor.read_log_tail(self.log, offset)
        self.assertEqual(text2, "")
        self.assertEqual(offset2, offset)

    def test_missing_log_raises(self) -> None:
        with self.assertRaises(monitor.MonitorError):
            monitor.read_log_tail(self.root / "absent.log", 0)


if __name__ == "__main__":
    unittest.main()
