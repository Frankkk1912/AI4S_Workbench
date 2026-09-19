"""T6.6: legacy status output is unchanged by an approval sidecar."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "md_run_cli.py"


class ApprovalSidecarCompatibilityTests(unittest.TestCase):
    def run_cli(self, *args: object) -> None:
        subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            text=True,
            capture_output=True,
            check=True,
        )

    def test_legacy_status_ignores_approval_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "duration.json"
            manifest = root / "manifest.json"
            log = root / "md_prod.log"
            before = root / "before.json"
            after = root / "after.json"
            self.run_cli(
                "plan-duration",
                "--profile",
                "wsl2-gpu",
                "--system-mass-kda",
                80,
                "--atom-count",
                120000,
                "--output",
                plan,
            )
            manifest.write_text(
                json.dumps(
                    {"work_dir": str(root), "duration_plan": {"path": str(plan)}}
                ),
                encoding="utf-8",
            )
            log.write_text("Step 1000\n5.0 ns/day\n", encoding="utf-8")
            self.run_cli(
                "status",
                "--manifest",
                manifest,
                "--log",
                log,
                "--total-steps",
                10000,
                "--output",
                before,
            )
            (root / "md_approval.json").write_text(
                json.dumps({"artifact_type": "md_approval", "confirmed": True}),
                encoding="utf-8",
            )
            self.run_cli(
                "status",
                "--manifest",
                manifest,
                "--log",
                log,
                "--total-steps",
                10000,
                "--output",
                after,
            )
            before_data = json.loads(before.read_text(encoding="utf-8"))
            after_data = json.loads(after.read_text(encoding="utf-8"))
            for volatile in ("checked_at", "log_age_seconds"):
                before_data.pop(volatile)
                after_data.pop(volatile)
            self.assertEqual(before_data, after_data)


if __name__ == "__main__":
    unittest.main()
