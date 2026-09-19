"""T2.6: explanatory read/diff and read-only protected parameter fields."""

from __future__ import annotations

import json
import unittest

from web.backend.tests import helpers


def write_handoff(workspace):
    path = workspace / "handoff.json"
    path.write_text(
        json.dumps(
            {
                "artifact_type": "docking_to_md_handoff",
                "ligand": {
                    "force_field": "charmm-cgenff",
                    "protein_force_field": "CHARMM36-jul2022",
                    "topology": {
                        "path": str(workspace / "ligand.itp"),
                        "sha256": "x" * 64,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def write_topology(workspace):
    path = workspace / "topol.top"
    path.write_text(
        '#include "charmm36-jul2022.ff/forcefield.itp"\n#include "tip3p.itp"\n',
        encoding="utf-8",
    )
    return path


def write_mdp(workspace):
    path = workspace / "em.mdp"
    path.write_text("integrator = steep\nemtol = 500.0\n", encoding="utf-8")
    return path


class ParamsReadOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.tmp, self.workspace = helpers.make_client()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_defaults_expose_mdp_and_protected_fields(self) -> None:
        resp = self.client.get("/params/defaults", headers=helpers.auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mdp"]["em"]["parameters"]["integrator"], "steep")
        self.assertEqual(data["force_field"]["primary"], "CHARMM36")
        self.assertEqual(data["water_model"]["model"], "TIP3P")
        self.assertIn("force_field", data["protected_fields"])

    def test_diff_explains_default_vs_current(self) -> None:
        handoff = write_handoff(self.workspace)
        topo = write_topology(self.workspace)
        mdp = write_mdp(self.workspace)
        resp = self.client.get(
            f"/params/diff?handoff_path={handoff}&topology_path={topo}"
            f"&mdp_path={mdp}&stage=em",
            headers=helpers.auth_headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(
            data["force_field"]["current"], "CHARMM36-jul2022 (ligand charmm-cgenff)"
        )
        self.assertTrue(data["force_field"]["protected"])
        self.assertEqual(data["water_model"]["current"], "TIP3P")
        self.assertTrue(data["water_model"]["protected"])
        emtol = next(item for item in data["mdp"] if item["key"] == "emtol")
        self.assertEqual(emtol["default"], "1000.0")
        self.assertEqual(emtol["current"], "500.0")
        self.assertTrue(emtol["changed"])

    def test_protected_put_rejected_with_reason(self) -> None:
        resp = self.client.put(
            "/params/force_field",
            json={"value": "AMBER"},
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("read-only", resp.json()["detail"])

    def test_protected_patch_rejected_with_reason(self) -> None:
        resp = self.client.patch(
            "/params/topology",
            json={},
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("re-preparing", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
