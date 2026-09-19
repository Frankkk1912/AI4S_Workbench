"""T2.4: structured allowlist submission, injection rejection, idempotency."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from web.backend.tests import helpers


def write_manifest(work: Path) -> Path:
    manifest = work / "md_run_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact_type": "md_run_manifest",
                "work_dir": str(work.resolve()),
            }
        ),
        encoding="utf-8",
    )
    return manifest


class RunSubmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.tmp, self.workspace = helpers.make_client()
        self.work = self.workspace / "project"
        self.work.mkdir()
        self.manifest = write_manifest(self.work)
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        self.outside_manifest = write_manifest(outside)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _body(self, request_id: str = "req-1", **overrides):
        body = {
            "request_id": request_id,
            "project": "nrlp3",
            "stage": "em",
            "manifest_path": str(self.manifest),
            "stage_plan": {
                "deffnm": "em",
                "profile": "linux-gpu",
                "threads": 8,
                "resume": False,
            },
        }
        body.update(overrides)
        return body

    def _post(self, body):
        return self.client.post(
            "/runs",
            json=body,
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        )

    def test_valid_submission_creates_idempotent_run(self) -> None:
        resp = self._post(self._body())
        self.assertEqual(resp.status_code, 201, resp.text)
        first = resp.json()
        self.assertEqual(first["stage"], "em")
        self.assertEqual(first["command"][:2], ["gmx", "mdrun"])
        self.assertEqual(first["plan_sha256"].__len__(), 64)

        again = self._post(self._body())
        self.assertEqual(again.status_code, 201)
        self.assertEqual(again.json()["run_id"], first["run_id"])
        self.assertFalse(again.json()["created"])

    def test_unknown_top_level_field_rejected(self) -> None:
        resp = self._post(self._body(unknown="x"))
        self.assertEqual(resp.status_code, 422)

    def test_unknown_stage_plan_field_rejected(self) -> None:
        body = self._body()
        body["stage_plan"]["shell"] = "true"
        resp = self._post(body)
        self.assertEqual(resp.status_code, 422)

    def test_injection_deffnm_rejected(self) -> None:
        body = self._body()
        body["stage_plan"]["deffnm"] = "em; rm -rf /"
        resp = self._post(body)
        self.assertEqual(resp.status_code, 400)

    def test_injection_profile_rejected(self) -> None:
        body = self._body()
        body["stage_plan"]["profile"] = "linux-gpu; touch /tmp/pwned"
        resp = self._post(body)
        self.assertEqual(resp.status_code, 422)

    def test_write_requires_csrf_header(self) -> None:
        resp = self.client.post(
            "/runs", json=self._body(), headers=helpers.auth_headers()
        )
        self.assertEqual(resp.status_code, 403)

    def test_manifest_outside_workspace_rejected(self) -> None:
        body = self._body(manifest_path=str(self.outside_manifest))
        resp = self._post(body)
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
