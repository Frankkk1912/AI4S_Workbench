# pyright: reportMissingImports=false
"""T6.8: same-origin static frontend and one-time browser token handoff."""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web.backend.app import create_app
from web.backend.config import create_token_file
from web.backend.tests import helpers
from web.backend.token_handoff import announce_once


class TokenHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.tmp, self.workspace = helpers.make_client()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_handoff_sets_httponly_cookie_used_by_api_and_sse(self) -> None:
        response = self.client.post(
            "/auth/handoff",
            headers={"X-AI4S-Request": "1"},
            json={"access_token": helpers.TOKEN},
        )
        self.assertEqual(response.status_code, 200, response.text)
        cookie = response.headers.get("set-cookie", "").lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)

        api_response = self.client.get("/params/defaults")
        self.assertEqual(api_response.status_code, 200, api_response.text)
        empty_bearer = self.client.get(
            "/params/defaults", headers={"Authorization": "Bearer "}
        )
        self.assertEqual(empty_bearer.status_code, 200, empty_bearer.text)

        log = self.workspace / "md.log"
        log.write_text("Step 1\n", encoding="utf-8")
        stream_response = self.client.get(
            f"/stream/log?log={log}&total_steps=10"
        )
        self.assertEqual(stream_response.status_code, 200, stream_response.text)
        self.assertIn("event: log", stream_response.text)

    def test_invalid_handoff_and_forged_origin_fail_closed(self) -> None:
        invalid = self.client.post(
            "/auth/handoff",
            headers={"X-AI4S-Request": "1"},
            json={"access_token": "wrong"},
        )
        self.assertEqual(invalid.status_code, 401)
        forged = self.client.post(
            "/auth/handoff",
            headers={
                "X-AI4S-Request": "1",
                "Origin": "http://evil.example.com",
            },
            json={"access_token": helpers.TOKEN},
        )
        self.assertEqual(forged.status_code, 403)

    def test_startup_handoff_is_announced_once(self) -> None:
        messages: list[str] = []
        announce_once(helpers.TOKEN, messages.append)
        self.assertEqual(len(messages), 1)
        self.assertIn(helpers.TOKEN, messages[0])

    def test_token_file_never_broadens_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "access"
            create_token_file(path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class StaticFrontendTests(unittest.TestCase):
    def test_frontend_is_same_origin_and_api_still_requires_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            frontend = root / "dist"
            workspace.mkdir()
            frontend.mkdir()
            (frontend / "index.html").write_text(
                "<html><body>same-origin-workbench</body></html>", encoding="utf-8"
            )
            app = create_app(
                token=helpers.TOKEN,
                workspace_roots=[workspace],
                db_path=root / "runner.db",
                frontend_dist=frontend,
            )
            client = TestClient(app, base_url="http://127.0.0.1")
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("same-origin-workbench", page.text)
            self.assertEqual(client.get("/params/defaults").status_code, 401)


if __name__ == "__main__":
    unittest.main()
