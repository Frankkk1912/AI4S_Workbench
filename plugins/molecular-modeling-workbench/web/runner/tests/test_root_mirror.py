"""Root `skills/` mirror consistency (T6.5(a), resolved by user decision).

The repository keeps a second, root-level `skills/` mirror of the plugin's
`source-skills/`. Any source change must be copied there byte-for-byte in the
same batch. This test asserts the mirror has the same file set and the same
SHA-256 content as the source for every molecular-modeling skill, so drift is
caught before it silently diverges. Generated Python caches are ignored.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = PLUGIN_ROOT.parents[1]
SOURCE_ROOT = PLUGIN_ROOT / "source-skills"
ROOT_SKILLS = REPO_ROOT / "skills"

SKILLS = [
    "md-simulation-run",
]


def _file_tree(root: Path) -> dict[str, str]:
    tree: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            tree[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return tree


class RootMirrorTests(unittest.TestCase):
    def test_root_skills_mirror_matches_source_skills(self) -> None:
        for skill in SKILLS:
            source = SOURCE_ROOT / skill
            mirror = ROOT_SKILLS / skill
            self.assertTrue(source.is_dir(), f"missing source skill {skill}")
            self.assertTrue(mirror.is_dir(), f"missing root mirror {skill}")
            self.assertEqual(
                _file_tree(source),
                _file_tree(mirror),
                f"root mirror drift detected for {skill}",
            )


if __name__ == "__main__":
    unittest.main()
