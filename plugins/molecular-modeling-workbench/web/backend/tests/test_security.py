"""T2.2: Host allowlist, same-origin check, and CSRF custom header."""

from __future__ import annotations

import unittest

from fastapi import HTTPException
from web.backend import security
from web.backend.tests import helpers


class HostOriginUnitTests(unittest.TestCase):
    def test_validate_host_rejects_untrusted(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            security.validate_host("evil.example.com")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_validate_host_accepts_loopback_with_port(self) -> None:
        self.assertEqual(security.validate_host("127.0.0.1:8765"), "127.0.0.1")
        self.assertEqual(security.validate_host("localhost:8765"), "localhost")

    def test_same_origin_passes(self) -> None:
        security.validate_origin("http://127.0.0.1:8765", "127.0.0.1:8765")

    def test_cross_origin_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            security.validate_origin("http://evil.example.com", "127.0.0.1")

    def test_origin_host_mismatch_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            security.validate_origin("http://127.0.0.1", "localhost")


class SecurityIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.tmp, self.workspace = helpers.make_client()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_forged_host_rejected_with_valid_token(self) -> None:
        resp = self.client.get(
            "/params/defaults",
            headers=helpers.auth_headers(host="evil.example.com"),
        )
        self.assertEqual(resp.status_code, 403)

    def test_forged_origin_rejected_with_valid_token(self) -> None:
        resp = self.client.get(
            "/params/defaults",
            headers=helpers.auth_headers(
                host="127.0.0.1", origin="http://evil.example.com"
            ),
        )
        self.assertEqual(resp.status_code, 403)

    def test_same_origin_passes_with_valid_token(self) -> None:
        resp = self.client.get(
            "/params/defaults",
            headers=helpers.auth_headers(host="127.0.0.1", origin="http://127.0.0.1"),
        )
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
