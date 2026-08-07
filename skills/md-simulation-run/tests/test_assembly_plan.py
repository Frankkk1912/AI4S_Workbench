import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ASSEMBLY = Path(__file__).parents[1] / "scripts" / "protein_ligand_assembly.py"
SYSTEM = Path(__file__).parents[1] / "scripts" / "protein_ligand_system.py"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(path):
    return {"path": str(path), "sha256": digest(path)}


class AssemblyPlanTests(unittest.TestCase):
    def invoke(self, script, *args, check=True, env=None):
        return subprocess.run([sys.executable, str(script), *map(str, args)], text=True, capture_output=True, check=check, env=env)

    def test_plan_binds_inputs_and_requires_preion_warning_rationale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docker = root / "docker"; docker.write_text("#!/bin/sh\n"); docker.chmod(0o755)
            receipt = root / "receipt.json"; receipt.write_text(json.dumps({"schema_version":"1.1","artifact_type":"molecular_modeling_environment_receipt","created_at":dt.datetime.now(dt.timezone.utc).isoformat(),"profile":"wsl2-gpu","ready":True,"report":{"tools":{"docker":{"available":True,"path":str(docker)}},"gromacs_container":{"available":True,"digest":"nvcr.io/nvidia/gromacs@sha256:" + "a" * 64}}}))
            pose = root / "pose.pdbqt"; pose.write_text("MODEL 1\nENDMDL\n")
            ligand = root / "BNZ.itp"; ligand.write_text("[ moleculetype ]\nBNZ 3\n")
            ligand_gro = root / "BNZ.gro"; ligand_gro.write_text("BNZ\n0\n   1 1 1\n")
            receptor = root / "receptor.pdb"; receptor.write_text("END\n")
            termini = root / "termini.json"; termini.write_text(json.dumps({"schema_version":"1.0","artifact_type":"protein_termini_record","chains":[{"chain_id":"A","n_terminus":"NH3+","c_terminus":"COO-"}]}))
            handoff = root / "handoff.json"; handoff.write_text(json.dumps({"schema_version":"1.0","artifact_type":"docking_to_md_handoff","system_type":"protein-ligand","selection":{"coordinates":reference(pose)},"ligand":{"applicable":True,"force_field":"amber-gaff","force_field_family":"amber","protein_force_field":"amber99sb-ildn","topology":reference(ligand),"coordinates":reference(ligand_gro),"validation":{"status":"validated"}},"validation":{"status":"validated"}}))
            system_plan = root / "system.json"
            ok = self.invoke(SYSTEM,"plan","--handoff",handoff,"--environment-receipt",receipt,"--receptor-pdb",receptor,"--termini-record",termini,"--water-model","tip3p","--box-shape","dodecahedron","--box-distance-nm","1.2","--salt-molar","0.15","--output",system_plan)
            self.assertEqual(ok.returncode,0,ok.stderr)
            top = root / "topol.top"; top.write_text("topology\n")
            gro = root / "protein.gro"; gro.write_text("protein\n0\n   1 1 1\n")
            protein = root / "protein.json"; protein.write_text(json.dumps({"artifact_type":"reviewed_protein_preparation","status":"reviewed","protein_topology":reference(top),"protein_coordinates":reference(gro)}))
            aligned = root / "aligned.json"; aligned.write_text(json.dumps({"heavy_atom_rmsd_nm":0.001}))
            ions = root / "ions.mdp"; ions.write_text("integrator = steep\n")
            em = root / "em.mdp"; em.write_text("integrator = steep\n")
            output = root / "assembly.json"
            fail = self.invoke(ASSEMBLY,"plan","--system-plan",system_plan,"--protein-preparation",protein,"--alignment-report",aligned,"--ligand-topology",ligand,"--ions-mdp",ions,"--em-mdp",em,"--work-dir",root/"work","--profile","wsl2-gpu","--preion-maxwarn","1","--output",output,check=False)
            self.assertNotEqual(fail.returncode,0); self.assertIn("rationale",fail.stderr)
            good = self.invoke(ASSEMBLY,"plan","--system-plan",system_plan,"--protein-preparation",protein,"--alignment-report",aligned,"--ligand-topology",ligand,"--ions-mdp",ions,"--em-mdp",em,"--work-dir",root/"work","--profile","wsl2-gpu","--preion-maxwarn","1","--preion-warning-rationale","Reviewed pre-ionization net charge warning.","--output",output)
            self.assertEqual(good.returncode,0,good.stderr)
            plan = json.loads(output.read_text())
            self.assertEqual(plan["commands"][0][1],"editconf")
            self.assertEqual(plan["commands"][-1][1],"grompp")
            self.assertEqual(len(plan["plan_sha256"]),64)

    def test_assemble_cpu_only_fake_docker_preserves_genion_stdin_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docker = root / "docker"
            docker.write_text("""#!%s
import json, os, pathlib, shutil, sys
args=sys.argv[1:]
if '-i' not in args or '--gpus' not in args or 'all' not in args: raise SystemExit(17)
mount=args[args.index('-v')+1].split(':/work',1)[0]; work=pathlib.Path(mount)
gmx=args[args.index('gmx'):]; (work/'fake_docker.jsonl').open('a').write(json.dumps(gmx)+'\\n')
if gmx[1]=='genion' and sys.stdin.read() != 'SOL\\n': raise SystemExit(18)
if os.environ.get('FAKE_DOCKER_FAIL') == gmx[1]: raise SystemExit(19)
def value(flag): return gmx[gmx.index(flag)+1]
if gmx[1] in ('editconf','solvate','genion'):
    out=work/value('-o'); out.write_text('fake\\n1\\n    1SOL  OW    1   0.000   0.000   0.000\\n   1.0   1.0   1.0\\n')
if gmx[1]=='grompp': (work/value('-o')).write_text('fake tpr\\n')
if gmx[1]=='solvate': (work/'topol.top').open('a').write('SOL 10\\n')
if gmx[1]=='genion': (work/'topol.top').open('a').write('NA 1\\nCL 1\\n')
""" % sys.executable)
            docker.chmod(0o755)
            receipt = root / "receipt.json"; receipt.write_text(json.dumps({"schema_version":"1.1","artifact_type":"molecular_modeling_environment_receipt","created_at":dt.datetime.now(dt.timezone.utc).isoformat(),"profile":"wsl2-gpu","ready":True,"report":{"tools":{"docker":{"available":True,"path":str(docker)}},"gromacs_container":{"available":True,"digest":"example@sha256:" + "b"*64}}}))
            pose=root/"pose.pdbqt"; pose.write_text("MODEL 1\nENDMDL\n")
            ligand=root/"BNZ.itp"; ligand.write_text("[ atomtypes ]\nC C 1 0 A 0.1 0.1\n[ moleculetype ]\nBNZ 3\n")
            ligand_gro=root/"BNZ.gro"; ligand_gro.write_text("BNZ\n1\n    1BNZ   C1    1   0.000   0.000   0.000\n   1.0   1.0   1.0\n")
            receptor=root/"receptor.pdb"; receptor.write_text("END\n")
            termini=root/"termini.json"; termini.write_text(json.dumps({"schema_version":"1.0","artifact_type":"protein_termini_record","chains":[{"chain_id":"A","n_terminus":"NH3+","c_terminus":"COO-"}]}))
            handoff=root/"handoff.json"; handoff.write_text(json.dumps({"schema_version":"1.0","artifact_type":"docking_to_md_handoff","system_type":"protein-ligand","selection":{"coordinates":reference(pose)},"ligand":{"applicable":True,"force_field":"amber-gaff","force_field_family":"amber","protein_force_field":"amber99sb-ildn","topology":reference(ligand),"coordinates":reference(ligand_gro),"validation":{"status":"validated"}},"validation":{"status":"validated"}}))
            system=root/"system.json"; self.invoke(SYSTEM,"plan","--handoff",handoff,"--environment-receipt",receipt,"--receptor-pdb",receptor,"--termini-record",termini,"--water-model","tip3p","--box-shape","dodecahedron","--box-distance-nm","1.2","--salt-molar","0.15","--output",system)
            top=root/"topol.top"; top.write_text('#include "amber99sb-ildn.ff/forcefield.itp"\n[ system ]\nTest\n[ molecules ]\nProtein 1\n')
            gro=root/"protein.gro"; gro.write_text("protein\n1\n    1ALA    N    1   0.000   0.000   0.000\n   1.0   1.0   1.0\n")
            protein=root/"protein.json"; protein.write_text(json.dumps({"artifact_type":"reviewed_protein_preparation","status":"reviewed","protein_topology":reference(top),"protein_coordinates":reference(gro)}))
            aligned=root/"aligned.json"; aligned.write_text(json.dumps({"heavy_atom_rmsd_nm":0.001,"coordinates":reference(ligand_gro)}))
            ions=root/"ions.mdp"; ions.write_text("integrator=steep\n"); em=root/"em.mdp"; em.write_text("integrator=steep\n")
            work=root/"work"; plan=root/"plan.json"; self.invoke(ASSEMBLY,"plan","--system-plan",system,"--protein-preparation",protein,"--alignment-report",aligned,"--ligand-topology",ligand,"--ions-mdp",ions,"--em-mdp",em,"--work-dir",work,"--profile","wsl2-gpu","--preion-maxwarn","0","--output",plan)
            receipt_out=root/"assembly.json"; done=self.invoke(ASSEMBLY,"assemble","--plan",plan,"--system-plan",system,"--protein-preparation",protein,"--alignment-report",aligned,"--ligand-topology",ligand,"--ions-mdp",ions,"--em-mdp",em,"--output",receipt_out,check=False)
            self.assertEqual(done.returncode,0,done.stderr + (work/"assembly_composition.log").read_text())
            result=json.loads(receipt_out.read_text()); self.assertEqual(result["status"],"completed"); self.assertEqual(result["system"]["molecule_counts"]["NA"],1)
            commands=[json.loads(line) for line in (work/"fake_docker.jsonl").read_text().splitlines()]
            self.assertEqual([cmd[1] for cmd in commands],["editconf","solvate","grompp","genion","grompp"])
            self.assertTrue(all(item["log"]["sha256"] for item in result["commands"]))
            failed_out=root/"assembly_failed.json"; env={**os.environ,"FAKE_DOCKER_FAIL":"genion"}
            failed=self.invoke(ASSEMBLY,"assemble","--plan",plan,"--system-plan",system,"--protein-preparation",protein,"--alignment-report",aligned,"--ligand-topology",ligand,"--ions-mdp",ions,"--em-mdp",em,"--output",failed_out,check=False,env=env)
            self.assertNotEqual(failed.returncode,0)
            self.assertEqual(json.loads(failed_out.read_text())["status"],"failed")


if __name__ == "__main__":
    unittest.main()
