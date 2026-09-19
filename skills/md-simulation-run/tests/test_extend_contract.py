"""T3.4: audited continuation TPR from a frozen checkpoint (plan-extend/extend).

The approval targets the total-duration/extension strategy (never a hash of a
still-changing checkpoint). `plan-extend` binds the original TPR, a frozen
checkpoint, and the approval reference into a derived, plan-hash-gated plan;
`extend` re-verifies every input and runs `gmx convert-tpr` through the same
receipt-bound docker path. The original TPR and manifest are preserved and the
completed-stage protection is not rewritten.
"""

import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "md_run_cli.py"
SPEC = importlib.util.spec_from_file_location("md_run_cli", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"Cannot load md_run_cli from {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strategy_hash(strategy: dict) -> str:
    return hashlib.sha256(
        json.dumps(strategy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class ExtendContractTests(unittest.TestCase):
    def run_cli(self, *args, check=True, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            text=True,
            capture_output=True,
            check=check,
            env=env,
        )

    def fixture(self, root: Path, stage: str = "md_prod") -> dict:
        work = root / "work"
        work.mkdir()
        # Fake docker creates the `-o` output (convert-tpr result).
        docker = root / "receipt-docker"
        docker.write_text(
            f"""#!{sys.executable}
import pathlib, sys
args = sys.argv[1:]
mount = pathlib.Path(args[args.index('-v') + 1].split(':/work', 1)[0])
gmx = args[args.index('gmx'):]
out = mount / gmx[gmx.index('-o') + 1]
out.write_text('fake extended tpr output\\n')
"""
        )
        docker.chmod(0o755)
        image_digest = "nvcr.io/nvidia/gromacs@sha256:" + "a" * 64
        receipt = root / "environment_receipt.json"
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
                    "artifact_type": "molecular_modeling_environment_receipt",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "profile": "wsl2-gpu",
                    "ready": True,
                    "report": {
                        "tools": {"docker": {"available": True, "path": str(docker)}},
                        "gromacs_container": {
                            "available": True,
                            "digest": image_digest,
                        },
                    },
                }
            )
        )
        stage_plan = root / f"{stage}_stage_plan.json"
        self.run_cli(
            "plan-stage",
            "--stage",
            stage,
            "--deffnm",
            stage,
            "--profile",
            "wsl2-gpu",
            "--threads",
            "8",
            "--output",
            stage_plan,
        )
        tpr = work / f"{stage}.tpr"
        tpr.write_text("original tpr\n")
        cpt = work / f"{stage}.cpt"
        cpt.write_text("frozen checkpoint\n")
        strategy = {
            "stages": [stage],
            "duration_ns": 250.0,
            "extension_ns": 100.0,
            "constraints": {"profile": "wsl2-gpu"},
        }
        approval = root / "extension_approval.json"
        approval.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "artifact_type": "md_approval",
                    "approval_id": "appr-ext-1",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "kind": "extension",
                    "strategy": strategy,
                    "strategy_hash": strategy_hash(strategy),
                    "confirmed": True,
                }
            )
        )
        source_boundary = root / "frozen_boundary.json"
        source_boundary.write_text(
            json.dumps(
                {
                    "artifact_type": "md_frozen_checkpoint",
                    "frozen": True,
                    "checkpoint": {"path": str(cpt.resolve()), "sha256": digest(cpt)},
                }
            )
        )
        manifest = root / "md_run_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "artifact_type": "md_run_manifest",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "work_dir": str(work.resolve()),
                    "duration_plan": {"profile": "wsl2-gpu"},
                    "environment_receipt": {
                        "path": str(receipt.resolve()),
                        "ready": True,
                    },
                    "stages": {},
                }
            )
        )
        return {
            "work": work,
            "receipt": receipt,
            "image_digest": image_digest,
            "stage_plan": stage_plan,
            "manifest": manifest,
            "tpr": tpr,
            "cpt": cpt,
            "approval": approval,
            "source_boundary": source_boundary,
            "stage": stage,
        }

    def plan_extend(self, fixture, root: Path, *extra):
        output = root / "extend_plan.json"
        args = [
            "plan-extend",
            "--manifest",
            fixture["manifest"],
            "--stage-plan",
            fixture["stage_plan"],
            "--tpr",
            fixture["tpr"],
            "--cpt",
            fixture["cpt"],
            "--approval",
            fixture["approval"],
            "--source-boundary",
            fixture["source_boundary"],
        ]
        args.extend(extra)
        args.extend(["--output", output])
        return self.run_cli(*args, check=False), output

    def extend(self, fixture, root: Path, plan: Path):
        output = root / "extend_receipt.json"
        result = self.run_cli(
            "extend",
            "--plan",
            plan,
            "--manifest",
            fixture["manifest"],
            "--stage-plan",
            fixture["stage_plan"],
            "--tpr",
            fixture["tpr"],
            "--cpt",
            fixture["cpt"],
            "--approval",
            fixture["approval"],
            "--source-boundary",
            fixture["source_boundary"],
            "--output",
            output,
            check=False,
        )
        return result, output

    def test_plan_extend_binds_frozen_cpt_approval_and_original_tpr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root)
            result, output = self.plan_extend(fixture, root, "--extend-ns", "100")
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(output.read_text())
            self.assertEqual(plan["artifact_type"], "md_extend_plan")
            # binds the FROZEN checkpoint and the approval reference, not a
            # still-changing cpt
            self.assertEqual(plan["inputs"]["cpt"]["sha256"], digest(fixture["cpt"]))
            self.assertEqual(
                plan["inputs"]["approval"]["sha256"], digest(fixture["approval"])
            )
            self.assertEqual(plan["inputs"]["tpr"]["sha256"], digest(fixture["tpr"]))
            # extension is convert-tpr with the ORIGINAL tpr as explicit -s input
            self.assertEqual(
                plan["command"],
                [
                    "gmx",
                    "convert-tpr",
                    "-s",
                    "md_prod.tpr",
                    "-o",
                    "md_prod_ext.tpr",
                    "-extend",
                    "100000",
                ],
            )
            self.assertEqual(plan["continuation"]["lineage"]["source_stage"], "md_prod")
            self.assertEqual(len(plan["plan_sha256"]), 64)

    def test_plan_extend_rejects_unfrozen_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root)
            boundary = json.loads(fixture["source_boundary"].read_text())
            boundary["frozen"] = False
            fixture["source_boundary"].write_text(json.dumps(boundary))
            result, _ = self.plan_extend(fixture, root, "--extend-ns", "100")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not frozen", result.stderr)
            # a boundary that does not match the cpt hash is also refused
            boundary["frozen"] = True
            boundary["checkpoint"]["sha256"] = "0" * 64
            fixture["source_boundary"].write_text(json.dumps(boundary))
            result, _ = self.plan_extend(fixture, root, "--extend-ns", "100")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match", result.stderr)

    def test_plan_extend_requires_exactly_one_extension_amount(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root)
            result, _ = self.plan_extend(fixture, root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly one", result.stderr)
            result, _ = self.plan_extend(
                fixture, root, "--extend-ns", "100", "--nsteps", "50"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly one", result.stderr)

    def test_extend_rejects_tampered_original_tpr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root)
            result, plan = self.plan_extend(fixture, root, "--extend-ns", "100")
            self.assertEqual(result.returncode, 0, result.stderr)
            fixture["tpr"].write_text("tampered original tpr\n")
            result, _ = self.extend(fixture, root, plan)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("tpr input does not match", result.stderr)

    def test_extend_produces_new_tpr_with_lineage_and_preserves_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root)
            result, plan = self.plan_extend(fixture, root, "--extend-ns", "100")
            self.assertEqual(result.returncode, 0, result.stderr)
            original_tpr_bytes = fixture["tpr"].read_bytes()
            original_manifest_bytes = fixture["manifest"].read_bytes()
            result, output = self.extend(fixture, root, plan)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(output.read_text())
            self.assertEqual(receipt["artifact_type"], "md_extend_receipt")
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(
                receipt["new_tpr"]["path"],
                str((fixture["work"] / "md_prod_ext.tpr").resolve()),
            )
            self.assertEqual(receipt["frozen_cpt"]["sha256"], digest(fixture["cpt"]))
            self.assertEqual(
                receipt["continuation"]["lineage"]["parent_approval"], "appr-ext-1"
            )
            # new TPR is a distinct artifact with its own receipt
            self.assertNotEqual(receipt["new_tpr"]["sha256"], digest(fixture["tpr"]))
            # the original TPR and manifest are preserved byte-for-byte
            self.assertEqual(fixture["tpr"].read_bytes(), original_tpr_bytes)
            self.assertEqual(fixture["manifest"].read_bytes(), original_manifest_bytes)
            self.assertNotIn(
                "md_prod",
                json.loads(fixture["manifest"].read_text()).get("stages", {}),
            )

    def test_extend_rejects_broken_plan_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root)
            result, plan = self.plan_extend(fixture, root, "--extend-ns", "100")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(plan.read_text())
            data["plan_sha256"] = "0" * 64
            plan.write_text(json.dumps(data))
            result, _ = self.extend(fixture, root, plan)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hash", result.stderr)

    def test_existing_subcommands_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root)
            # plan-stage and plan-launch still work as before
            self.assertEqual(fixture["stage_plan"].is_file(), True)
            stage_plan = json.loads(fixture["stage_plan"].read_text())
            self.assertEqual(stage_plan["artifact_type"], "md_stage_plan")
            self.assertEqual(MODULE.STAGE_ORDER, ("em", "nvt", "npt", "md_prod"))
            # foreground gromacs_command keeps its pre-existing --rm behavior
            receipt = json.loads(fixture["receipt"].read_text())
            vector = MODULE.gromacs_command(
                receipt, fixture["work"], ["gmx", "mdrun", "-deffnm", "md_prod"]
            )
            self.assertIn("--rm", vector)
            self.assertNotIn("-d", vector)


if __name__ == "__main__":
    unittest.main()
