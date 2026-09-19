"""T2.3: workspace containment, symlink escape, and cross-project isolation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from web.backend import paths


class WorkspacePathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "workspace"
        self.ws.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_inside_root_resolves(self) -> None:
        target = self.ws / "sub" / "file.txt"
        target.parent.mkdir()
        target.write_text("x", encoding="utf-8")
        resolved = paths.resolve_workspace_path([self.ws], target, must_exist=True)
        self.assertEqual(resolved, target.resolve())

    def test_dotdot_escape_rejected(self) -> None:
        with self.assertRaises(paths.PathEscapeError):
            paths.resolve_workspace_path(
                [self.ws], self.ws / ".." / "outside" / "file.txt"
            )

    def test_symlink_escape_rejected(self) -> None:
        link = self.ws / "link"
        link.symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(paths.PathEscapeError):
            paths.resolve_workspace_path([self.ws], link / "secret.txt")

    def test_cross_project_rejected(self) -> None:
        other = self.root / "other-project"
        other.mkdir()
        with self.assertRaises(paths.PathEscapeError):
            paths.resolve_workspace_path([self.ws], other / "file.txt")

    def test_must_exist_missing_rejected(self) -> None:
        with self.assertRaises(paths.PathNotFoundError):
            paths.resolve_workspace_path(
                [self.ws], self.ws / "missing.txt", must_exist=True
            )


if __name__ == "__main__":
    unittest.main()
