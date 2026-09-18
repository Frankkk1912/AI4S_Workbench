import datetime as dt
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "docking_run.py"
SPEC = importlib.util.spec_from_file_location("docking_run", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load docking_run test module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ScoreParsingTests(unittest.TestCase):
    def test_gnina_scores_keep_engine_specific_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "poses.pdbqt"
            output.write_text(
                "REMARK VINA RESULT: -7.2 0.0 0.0\n"
                "REMARK CNNscore 0.81\n"
                "REMARK CNNaffinity -8.4\n"
            )
            poses = MODULE.parse_scores("gnina", output)
            self.assertEqual(poses[0]["scores"]["gnina_vina_affinity_kcal_mol"], -7.2)
            self.assertEqual(poses[0]["scores"]["gnina_cnn_score"], 0.81)
            self.assertEqual(poses[0]["scores"]["gnina_cnn_affinity_kcal_mol"], -8.4)
            self.assertEqual(poses[0]["score_source"], "pdbqt_remark")

    def test_gnina_current_pdbqt_remarks_are_parsed_with_cnn_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "poses.pdbqt"
            output.write_text(
                "MODEL 1\n"
                "REMARK minimizedAffinity -5.47264194\n"
                "REMARK CNNscore 0.91090858\n"
                "REMARK CNNaffinity 4.17653465\n"
                "ENDMDL\n"
            )
            poses = MODULE.parse_scores("gnina", output)
            self.assertEqual(len(poses), 1)
            self.assertEqual(
                poses[0]["scores"]["gnina_vina_affinity_kcal_mol"], -5.47264194
            )
            self.assertEqual(poses[0]["scores"]["gnina_cnn_score"], 0.91090858)
            self.assertEqual(
                poses[0]["scores"]["gnina_cnn_affinity_kcal_mol"], 4.17653465
            )
            self.assertEqual(poses[0]["score_source"], "pdbqt_remark")

    def test_vina_log_table_fallback_when_pdbqt_lacks_remarks(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "poses.pdbqt"
            output.write_text("ATOM      1  C1  LIG A   1       1.0   2.0   3.0\nEND\n")
            log = Path(tmp) / "vina.log"
            log.write_text(
                "mode |   affinity | dist from best mode\n"
                "     | (kcal/mol) | rmsd l.b.| rmsd u.b.\n"
                "-----+------------+----------+----------\n"
                "   1       -8.5      0.000      0.000\n"
                "   2       -7.9      1.234      2.345\n"
                "\n"
            )
            poses = MODULE.parse_scores("vina", output, log)
            self.assertEqual(len(poses), 2)
            self.assertEqual(poses[0]["scores"]["vina_affinity_kcal_mol"], -8.5)
            self.assertEqual(poses[1]["scores"]["vina_affinity_kcal_mol"], -7.9)
            self.assertEqual(poses[0]["score_source"], "engine_log_table")

    def test_gnina_log_table_fallback_recovers_cnn_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "poses.pdbqt"
            output.write_text("END\n")
            log = Path(tmp) / "gnina.log"
            log.write_text(
                "mode |  affinity  |    CNN     |     CNN\n"
                "     | (kcal/mol) | score      | affinity\n"
                "-----+------------+------------+----------\n"
                "   1       -9.12      0.847      7.231\n"
                "\n"
            )
            poses = MODULE.parse_scores("gnina", output, log)
            self.assertEqual(len(poses), 1)
            self.assertEqual(poses[0]["scores"]["gnina_vina_affinity_kcal_mol"], -9.12)
            self.assertEqual(poses[0]["scores"]["gnina_cnn_score"], 0.847)
            self.assertEqual(poses[0]["scores"]["gnina_cnn_affinity_kcal_mol"], 7.231)
            self.assertEqual(poses[0]["score_source"], "engine_log_table")

    def test_gnina_minimized_affinity_last_resort(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "poses.pdbqt"
            output.write_text("")
            log = Path(tmp) / "gnina.log"
            log.write_text("minimizedAffinity: -8.77\nminimizedAffinity: -8.01\n")
            poses = MODULE.parse_scores("gnina", output, log)
            self.assertEqual(len(poses), 2)
            self.assertEqual(poses[0]["scores"]["gnina_vina_affinity_kcal_mol"], -8.77)
            self.assertEqual(poses[0]["score_source"], "gnina_minimized_affinity")

    def test_pdbqt_remarks_take_precedence_over_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "poses.pdbqt"
            output.write_text("REMARK VINA RESULT: -7.2 0.0 0.0\n")
            log = Path(tmp) / "vina.log"
            log.write_text("-----\n   1       -8.5\n\n")
            poses = MODULE.parse_scores("vina", output, log)
            self.assertEqual(len(poses), 1)
            self.assertEqual(poses[0]["score_source"], "pdbqt_remark")

    def test_missing_pdbqt_without_log_yields_no_poses(self):
        with tempfile.TemporaryDirectory() as tmp:
            poses = MODULE.parse_scores("vina", Path(tmp) / "absent.pdbqt")
            self.assertEqual(poses, [])

    def test_exports_individual_hash_bound_pose_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "poses.pdbqt"
            output.write_text(
                "MODEL 1\nREMARK VINA RESULT: -7.2 0.0 0.0\nATOM      1  C1  LIG A   1       1.0   2.0   3.0\nENDMDL\n"
                "MODEL 2\nREMARK VINA RESULT: -6.8 0.0 0.0\nATOM      1  C1  LIG A   1       4.0   5.0   6.0\nENDMDL\n"
            )
            poses = MODULE.parse_scores("vina", output)
            MODULE.export_pose_coordinates(output, poses, root / "individual-poses")
            first = poses[0]["coordinate_file"]
            second = poses[1]["coordinate_file"]
            self.assertEqual(
                first["path"],
                str((root / "individual-poses" / "pose_001.pdbqt").resolve()),
            )
            self.assertEqual(first["sha256"], MODULE.digest(Path(first["path"])))
            self.assertEqual(second["sha256"], MODULE.digest(Path(second["path"])))
            self.assertIn("1.0   2.0   3.0", Path(first["path"]).read_text())
            self.assertNotIn("4.0   5.0   6.0", Path(first["path"]).read_text())
            self.assertIn("4.0   5.0   6.0", Path(second["path"]).read_text())

    def test_successful_engine_run_records_individual_pose_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receptor = root / "receptor.pdbqt"
            receptor.write_text("RECEPTOR\n")
            ligand = root / "ligand.pdbqt"
            ligand.write_text("LIGAND\n")

            def fake_run(command, **_):
                output = Path(command[command.index("--out") + 1])
                output.write_text(
                    "MODEL 1\nREMARK VINA RESULT: -7.2 0.0 0.0\n"
                    "ATOM      1  C1  LIG A   1       1.0   2.0   3.0\nENDMDL\n"
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(MODULE.subprocess, "run", side_effect=fake_run):
                result = MODULE.run_engine(
                    "vina",
                    "fake-vina",
                    SimpleNamespace(receptor=str(receptor), ligand=str(ligand), seed=7),
                    [1.0, 2.0, 3.0],
                    [10.0, 10.0, 10.0],
                    root,
                )
            self.assertEqual(result["command"][0], "fake-vina")
            self.assertEqual(result["status"], "completed")
            coordinate = result["poses"][0]["coordinate_file"]
            self.assertTrue(Path(coordinate["path"]).is_file())
            self.assertEqual(
                coordinate["sha256"], MODULE.digest(Path(coordinate["path"]))
            )


class FallbackReasonTests(unittest.TestCase):
    def test_records_the_failed_primary_backend_reason(self):
        runs = [
            {
                "engine": "gnina",
                "status": "failed",
                "reason": "No valid pose output was produced.",
            },
            {"engine": "vina", "status": "completed", "reason": None},
        ]
        self.assertEqual(
            MODULE.backend_fallback_reason(runs, runs[1]),
            "No valid pose output was produced.",
        )


class VectorParsingTests(unittest.TestCase):
    def test_size_must_be_positive(self):
        with self.assertRaises(MODULE.DockingError):
            MODULE.parse_vector("20,-1,20", "size")

    def test_center_allows_negative(self):
        self.assertEqual(MODULE.parse_vector("-1,2,3", "center"), [-1.0, 2.0, 3.0])

    def test_vector_requires_three_components(self):
        with self.assertRaises(MODULE.DockingError):
            MODULE.parse_vector("1,2", "center")

    def test_receipt_rejects_unready_and_stale_state(self):
        receipt = {
            "schema_version": "1.1",
            "artifact_type": "molecular_modeling_environment_receipt",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "profile": "wsl2-gpu",
            "ready": True,
            "report": {"tools": {"gnina": {"available": True}}},
        }
        MODULE.validate_environment_receipt(receipt, "wsl2-gpu", "gnina")
        receipt["ready"] = False
        with self.assertRaisesRegex(MODULE.DockingError, "not ready"):
            MODULE.validate_environment_receipt(receipt, "wsl2-gpu", "gnina")
        receipt["ready"] = True
        receipt["created_at"] = "2000-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(MODULE.DockingError, "older than seven days"):
            MODULE.validate_environment_receipt(receipt, "wsl2-gpu", "gnina")

    def test_receipt_executable_requires_an_existing_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "vina"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            receipt = {
                "report": {
                    "tools": {"vina": {"available": True, "path": str(executable)}}
                }
            }
            self.assertEqual(
                MODULE.receipt_executable(receipt, "vina"), str(executable.resolve())
            )
            receipt["report"]["tools"]["vina"]["path"] = "vina"
            with self.assertRaisesRegex(
                MODULE.DockingError, "absolute executable path"
            ):
                MODULE.receipt_executable(receipt, "vina")


if __name__ == "__main__":
    unittest.main()
