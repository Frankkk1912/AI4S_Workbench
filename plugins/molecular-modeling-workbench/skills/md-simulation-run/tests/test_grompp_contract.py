import datetime as dt
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "md_run_cli.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": digest(path)}


class GromppContractTests(unittest.TestCase):
    def invoke(self, *args, check=True, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            text=True,
            capture_output=True,
            check=check,
            env=env,
        )

    def fixture(self, root: Path, stage: str, fail_code: int = 0):
        work = root / "work"
        work.mkdir()
        docker = root / "receipt-docker"
        docker.write_text(
            f"""#!{sys.executable}
import json, pathlib, sys
args=sys.argv[1:]
mount=pathlib.Path(args[args.index('-v')+1].split(':/work',1)[0])
gmx=args[args.index('gmx'):]
(mount/'fake_docker_command.json').write_text(json.dumps(sys.argv))
if {fail_code}:
    print('planned fake grompp failure', file=sys.stderr)
    raise SystemExit({fail_code})
out=mount/gmx[gmx.index('-o')+1]
out.write_text('fake tpr output\\n')
"""
        )
        docker.chmod(0o755)
        receipt = root / "environment_receipt.json"
        image_digest = "nvcr.io/nvidia/gromacs@sha256:" + "a" * 64
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
                        "gromacs_container": {"available": True, "digest": image_digest},
                    },
                }
            )
        )
        mdp = work / f"{stage}.mdp"
        mdp.write_text("integrator = md\ndt = 0.002\n")
        topology = work / "topol.top"
        topology.write_text("[ system ]\nTest\n")
        stage_plan = root / f"{stage}_stage_plan.json"
        self.invoke(
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
        stages = {}
        coordinate = work / "source.gro"
        coordinate.write_text("source\n0\n1 1 1\n")
        if stage != "em":
            predecessor = {"nvt": "em", "npt": "nvt", "md_prod": "npt"}[stage]
            coordinate = work / f"{predecessor}.gro"
            coordinate.write_text(f"{predecessor}\n0\n1 1 1\n")
            stages[predecessor] = {
                "status": "completed",
                "artifacts": {"gro": reference(coordinate)},
            }
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "artifact_type": "md_run_manifest",
                    "work_dir": str(work.resolve()),
                    "duration_plan": {"profile": "wsl2-gpu"},
                    "environment_receipt": {"path": str(receipt.resolve()), "ready": True},
                    "stages": stages,
                }
            )
        )
        return {
            "work": work,
            "docker": docker,
            "receipt": receipt,
            "image_digest": image_digest,
            "mdp": mdp,
            "topology": topology,
            "stage_plan": stage_plan,
            "manifest": manifest,
            "coordinate": coordinate,
        }

    def plan(self, fixture, stage: str, root: Path, *extra):
        output = root / f"{stage}_grompp_plan.json"
        args = [
            "plan-grompp",
            "--manifest",
            fixture["manifest"],
            "--stage-plan",
            fixture["stage_plan"],
            "--mdp",
            fixture["mdp"],
            "--topology",
            fixture["topology"],
            "--maxwarn",
            "0",
        ]
        if stage == "em":
            args.extend(["--coordinate", fixture["coordinate"]])
        args.extend(extra)
        args.extend(["--output", output])
        result = self.invoke(*args, check=False)
        return result, output

    def execute(self, fixture, stage: str, plan: Path, output: Path, env=None):
        args = [
            "grompp",
            "--plan",
            plan,
            "--manifest",
            fixture["manifest"],
            "--stage-plan",
            fixture["stage_plan"],
            "--mdp",
            fixture["mdp"],
            "--topology",
            fixture["topology"],
        ]
        if stage == "em":
            args.extend(["--coordinate", fixture["coordinate"]])
        args.extend(["--output", output])
        return self.invoke(*args, check=False, env=env)

    def test_em_plan_hash_binds_explicit_source_coordinate_and_allowed_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, "em")
            result, output = self.plan(fixture, "em", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(output.read_text())
            self.assertEqual(plan["inputs"]["coordinate"]["source"]["kind"], "explicit")
            self.assertEqual(plan["inputs"]["coordinate"]["sha256"], digest(fixture["coordinate"]))
            self.assertEqual(
                plan["command"],
                ["gmx", "grompp", "-f", "em.mdp", "-c", "source.gro", "-p", "topol.top", "-o", "em.tpr"],
            )
            self.assertEqual(plan["runtime"]["docker_path"], str(fixture["docker"].resolve()))
            self.assertEqual(plan["runtime"]["gromacs_image_digest"], fixture["image_digest"])

    def test_successor_uses_hash_protected_predecessor_and_rejects_explicit_coordinate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, "nvt")
            result, output = self.plan(fixture, "nvt", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(output.read_text())
            self.assertEqual(plan["inputs"]["coordinate"]["source"], {"kind": "predecessor_gro", "stage": "em"})
            self.assertIn("em.gro", plan["command"])
            rejected, _ = self.plan(fixture, "nvt", root, "--coordinate", fixture["coordinate"])
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("predecessor", rejected.stderr)

    def test_changed_mdp_and_predecessor_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, "nvt")
            result, plan = self.plan(fixture, "nvt", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            fixture["mdp"].write_text("integrator = changed\n")
            receipt = root / "changed_mdp_receipt.json"
            failed = self.execute(fixture, "nvt", plan, receipt)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("mdp input does not match", failed.stderr.lower())

    def test_changed_predecessor_is_rejected_during_planning_and_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, "npt")
            fixture["coordinate"].write_text("changed before planning\n")
            failed, _ = self.plan(fixture, "npt", root)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("hash changed", failed.stderr)

            root2 = root / "execution"
            root2.mkdir()
            fixture2 = self.fixture(root2, "npt")
            result, plan = self.plan(fixture2, "npt", root2)
            self.assertEqual(result.returncode, 0, result.stderr)
            fixture2["coordinate"].write_text("changed after planning\n")
            failed = self.execute(fixture2, "npt", plan, root2 / "receipt.json")
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("coordinate input hash changed", failed.stderr.lower())

    def test_execution_uses_receipt_bound_docker_command_and_records_tpr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, "em")
            result, plan = self.plan(fixture, "em", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt_path = root / "grompp_receipt.json"
            done = self.execute(fixture, "em", plan, receipt_path)
            self.assertEqual(done.returncode, 0, done.stderr)
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["command"][0], str(fixture["docker"].resolve()))
            self.assertIn(fixture["image_digest"], receipt["command"])
            self.assertEqual(receipt["artifacts"]["tpr"]["sha256"], digest(fixture["work"] / "em.tpr"))
            self.assertTrue(Path(receipt["log"]["path"]).is_file())

    def test_nonzero_grompp_writes_failed_receipt_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, "em", fail_code=23)
            result, plan = self.plan(fixture, "em", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt_path = root / "failed_grompp_receipt.json"
            failed = self.execute(fixture, "em", plan, receipt_path)
            self.assertNotEqual(failed.returncode, 0)
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["returncode"], 23)
            self.assertEqual(receipt["artifacts"], {})
            self.assertIn("planned fake grompp failure", Path(receipt["log"]["path"]).read_text())


if __name__ == "__main__":
    unittest.main()
