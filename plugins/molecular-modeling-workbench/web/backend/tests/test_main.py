"""T2.1: token file 0600, loopback binding, and no-token 401."""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from web.backend import config, main
from web.backend.tests import helpers


class TokenFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_token_file_is_0600_and_reusable(self) -> None:
        path = self.root / "token"
        token = config.create_token_file(path)
        self.assertTrue(token)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(config.load_or_create_token(path), token)

    def test_load_or_create_reuses_existing_token(self) -> None:
        path = self.root / "token"
        first = config.create_token_file(path)
        self.assertEqual(config.load_or_create_token(path), first)


class BindAddressTests(unittest.TestCase):
    def test_host_is_loopback_only(self) -> None:
        self.assertEqual(config.HOST, "127.0.0.1")
        self.assertEqual(main.HOST, "127.0.0.1")

    def test_uvicorn_config_binds_loopback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "ws"
            workspace.mkdir()
            cfg = main.uvicorn_config(root / "token", [workspace], root / "runner.db")
        self.assertEqual(cfg.host, "127.0.0.1")


class NoTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.tmp, self.workspace = helpers.make_client()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_api_without_token_returns_401(self) -> None:
        for url in ("/params/defaults", "/runs/someid"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 401, url)


if __name__ == "__main__":
    unittest.main()
