#!/usr/bin/env python3
"""Plan, execute, and verify hash-bound protein-ligand GROMACS assembly."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent
COMPOSE = ROOT / "protein_ligand_composition.py"

class AssemblyError(ValueError): pass

def load(path):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc: raise AssemblyError(f"Cannot read {Path(path).name}: {exc}") from exc

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(json.dumps(data, indent=2)+"\n", encoding="utf-8")
def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat()
def ref(path): return {"filename": Path(path).name, "sha256": sha(path)}
def require(path, label):
    path=Path(path)
    if not path.is_file() or path.stat().st_size == 0: raise AssemblyError(f"{label} is missing or empty.")
    return path.resolve()
def plan_hash(data): return hashlib.sha256(json.dumps({k:v for k,v in data.items() if k!="plan_sha256"},sort_keys=True,separators=(",", ":")).encode()).hexdigest()
def valid_plan(data):
    if data.get("artifact_type")!="protein_ligand_assembly_plan" or data.get("plan_sha256")!=plan_hash(data): raise AssemblyError("Assembly plan is invalid or changed.")
    return data

def protected(value, label):
    if not isinstance(value, dict) or not isinstance(value.get("path"),str) or not isinstance(value.get("sha256"),str): raise AssemblyError(f"{label} reference is incomplete.")
    p=require(value["path"], label)
    if sha(p)!=value["sha256"]: raise AssemblyError(f"{label} hash changed.")
    return p

def receipt_from_system_plan(system):
    return protected(system.get("inputs",{}).get("environment_receipt"), "environment receipt")

def validate_receipt(receipt_path, profile):
    receipt=load(receipt_path)
    if receipt.get("artifact_type")!="molecular_modeling_environment_receipt" or receipt.get("schema_version")!="1.1" or receipt.get("ready") is not True or receipt.get("profile")!=profile: raise AssemblyError("Environment receipt is not ready or profile-matched.")
    try: created=dt.datetime.fromisoformat(receipt["created_at"].replace("Z","+00:00"))
    except Exception as exc: raise AssemblyError("Environment receipt has invalid created_at.") from exc
    if dt.datetime.now(dt.timezone.utc)-created.astimezone(dt.timezone.utc)>dt.timedelta(days=7): raise AssemblyError("Environment receipt is older than seven days.")
    docker=receipt.get("report",{}).get("tools",{}).get("docker",{}); image=receipt.get("report",{}).get("gromacs_container",{})
    docker_path=Path(docker.get("path", "")); digest=image.get("digest")
    if not docker.get("available") or not docker_path.is_absolute() or not docker_path.is_file() or not os.access(docker_path,os.X_OK): raise AssemblyError("Environment receipt does not bind an executable Docker path.")
    if not image.get("available") or not isinstance(digest,str) or "@sha256:" not in digest: raise AssemblyError("Environment receipt does not bind a GROMACS image digest.")
    return receipt, str(docker_path.resolve()), digest

def build_plan(args):
    system_path=require(args.system_plan,"system preparation plan"); system=load(system_path)
    if system.get("artifact_type")!="protein_ligand_system_preparation_plan": raise AssemblyError("System preparation plan is unsupported.")
    receipt_path=receipt_from_system_plan(system); receipt, _, digest=validate_receipt(receipt_path,args.profile)
    protein=require(args.protein_preparation,"reviewed protein preparation"); alignment=require(args.alignment_report,"ligand alignment report"); ligand=require(args.ligand_topology,"ligand topology"); em=require(args.em_mdp,"EM MDP"); ions=require(args.ions_mdp,"ions MDP")
    reviewed=load(protein); aligned=load(alignment)
    if reviewed.get("status")!="reviewed" or reviewed.get("artifact_type")!="reviewed_protein_preparation": raise AssemblyError("Reviewed protein preparation is required.")
    if float(aligned.get("heavy_atom_rmsd_nm",99))>0.01: raise AssemblyError("Ligand pose alignment RMSD exceeds 0.01 nm.")
    if args.preion_maxwarn and not args.preion_warning_rationale: raise AssemblyError("A pre-ionization warning allowance requires a reviewed rationale.")
    data={"schema_version":"1.0","artifact_type":"protein_ligand_assembly_plan","created_at":stamp(),"profile":args.profile,"work_dir":str(args.work_dir.resolve()),"inputs":{"system_plan":ref(system_path),"protein_preparation":ref(protein),"alignment_report":ref(alignment),"ligand_topology":ref(ligand),"ions_mdp":ref(ions),"em_mdp":ref(em),"environment_receipt":ref(receipt_path)},"parameters":{"box_shape":system.get("parameters",{}).get("box_shape"),"box_distance_nm":system.get("parameters",{}).get("box_distance_nm"),"salt_molar":system.get("parameters",{}).get("salt_molar"),"preion_maxwarn":args.preion_maxwarn,"preion_warning_rationale":args.preion_warning_rationale},"gromacs_image_digest":digest,"commands":[["gmx","editconf","-f","complex.gro","-o","boxed.gro","-c","-d",str(system["parameters"]["box_distance_nm"]),"-bt",system["parameters"]["box_shape"]],["gmx","solvate","-cp","boxed.gro","-cs","spc216.gro","-o","solvated.gro","-p","topol.top"],["gmx","grompp","-f","ions.mdp","-c","solvated.gro","-p","topol.top","-o","ions.tpr","-maxwarn",str(args.preion_maxwarn)],["gmx","genion","-s","ions.tpr","-o","complex_ions.gro","-p","topol.top","-pname","NA","-nname","CL","-neutral","-conc",str(system["parameters"]["salt_molar"])],["gmx","grompp","-f","em.mdp","-c","complex_ions.gro","-p","topol.top","-o","em.tpr"]]}
    data["plan_sha256"]=plan_hash(data); return data

def docker_command(receipt,docker,digest,work,gmx):
    # -i is required for the deterministic SOL selection supplied to genion.
    return [docker,"run","--rm","-i","--user",f"{os.getuid()}:{os.getgid()}","--gpus","all","-v",f"{work}:/work","-w","/work",digest,*gmx]

def molecule_counts(topology):
    lines=Path(topology).read_text(encoding="utf-8").splitlines(); start=None
    for index,line in enumerate(lines):
        if line.strip().lower()=="[ molecules ]": start=index+1; break
    if start is None: raise AssemblyError("Final topology lacks [ molecules ].")
    counts={}
    for line in lines[start:]:
        line=line.split(";",1)[0].strip()
        if not line or line.startswith("["): continue
        fields=line.split()
        if len(fields)>=2:
            try: counts[fields[0]]=int(fields[1])
            except ValueError: raise AssemblyError("Final topology has invalid molecule count.")
    return counts

def write_failure_receipt(output, plan_path, digest, records, reason):
    write(output,{"schema_version":"1.0","artifact_type":"protein_ligand_assembly_receipt","created_at":stamp(),"status":"failed","plan":{"path":str(Path(plan_path).resolve()),"sha256":sha(plan_path)},"gromacs_image_digest":digest,"commands":records,"failure_reason":reason,"artifacts":{}})

def execute(args):
    plan=valid_plan(load(require(args.plan,"assembly plan"))); work=Path(plan["work_dir"]); work.mkdir(parents=True,exist_ok=True)
    supplied={"system_plan":args.system_plan,"protein_preparation":args.protein_preparation,"alignment_report":args.alignment_report,"ligand_topology":args.ligand_topology,"ions_mdp":args.ions_mdp,"em_mdp":args.em_mdp}
    for label,path in supplied.items():
        path=require(path,label)
        if ref(path)!=plan["inputs"][label]: raise AssemblyError(f"{label} does not match the assembly plan.")
    system=load(args.system_plan); receipt_path=receipt_from_system_plan(system); receipt,docker,digest=validate_receipt(receipt_path,plan["profile"])
    if ref(receipt_path)!=plan["inputs"]["environment_receipt"] or digest!=plan["gromacs_image_digest"]: raise AssemblyError("Environment receipt does not match the assembly plan.")
    composed=work/"composition.json"
    compose=[sys.executable,str(COMPOSE),"--protein-preparation",str(args.protein_preparation),"--alignment-report",str(args.alignment_report),"--ligand-topology",str(args.ligand_topology),"--output-dir",str(work),"--output",str(composed)]
    result=subprocess.run(compose,text=True,capture_output=True,check=False)
    composition_log=work/"assembly_composition.log"; composition_log.write_text(result.stdout+"\n--- STDERR ---\n"+result.stderr,encoding="utf-8")
    records=[{"step":"composition","command":compose,"returncode":result.returncode,"log":{"path":str(composition_log.resolve()),"sha256":sha(composition_log)}}]
    if result.returncode:
        write_failure_receipt(args.output,args.plan,digest,records,"Composition failed; inspect its local log.")
        raise AssemblyError("Composition failed; inspect its local log.")
    for source,name in ((args.ions_mdp,"ions.mdp"),(args.em_mdp,"em.mdp")):
        target=work/name
        target.write_bytes(Path(source).read_bytes())
    expected=["boxed.gro","solvated.gro","ions.tpr","complex_ions.gro","em.tpr"]
    for index,gmx in enumerate(plan["commands"]):
        command=docker_command(receipt,docker,digest,work,gmx)
        result=subprocess.run(command,input="SOL\n" if gmx[1]=="genion" else None,text=True,capture_output=True,check=False)
        log=work/f"assembly_{index + 1:02d}_{gmx[1]}.log"; log.write_text(result.stdout+"\n--- STDERR ---\n"+result.stderr,encoding="utf-8")
        records.append({"step":gmx[1],"command":command,"returncode":result.returncode,"log":{"path":str(log.resolve()),"sha256":sha(log)}})
        if result.returncode:
            reason=f"GROMACS {gmx[1]} failed; inspect its local log."
            write_failure_receipt(args.output,args.plan,digest,records,reason)
            raise AssemblyError(reason)
        require(work/expected[index], f"{gmx[1]} output")
    artifacts={name: {"path":str((work/name).resolve()),"sha256":sha(work/name)} for name in ("topol.top","complex.gro","boxed.gro","solvated.gro","ions.tpr","complex_ions.gro","em.tpr")}
    rows=(work/"complex_ions.gro").read_text(encoding="utf-8").splitlines()
    try: atom_count=int(rows[1])
    except Exception as exc: raise AssemblyError("Final GRO has invalid atom count.") from exc
    receipt_doc={"schema_version":"1.0","artifact_type":"protein_ligand_assembly_receipt","created_at":stamp(),"status":"completed","plan":{"path":str(Path(args.plan).resolve()),"sha256":sha(args.plan)},"gromacs_image_digest":digest,"commands":records,"system":{"atom_count":atom_count,"molecule_counts":molecule_counts(work/"topol.top")},"artifacts":artifacts}
    write(args.output,receipt_doc); print(f"Success! Data written to: {args.output}")

def verify(args):
    receipt=load(require(args.receipt,"assembly receipt"))
    if receipt.get("artifact_type")!="protein_ligand_assembly_receipt" or receipt.get("status")!="completed": raise AssemblyError("Assembly receipt is not completed.")
    for item in receipt.get("artifacts",{}).values():
        protected(item, "assembly artifact")
    print(f"Verified assembly receipt: {args.receipt}")

def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("plan"); q.add_argument("--system-plan",type=Path,required=True); q.add_argument("--protein-preparation",type=Path,required=True); q.add_argument("--alignment-report",type=Path,required=True); q.add_argument("--ligand-topology",type=Path,required=True); q.add_argument("--ions-mdp",type=Path,required=True); q.add_argument("--em-mdp",type=Path,required=True); q.add_argument("--work-dir",type=Path,required=True); q.add_argument("--profile",choices=("wsl2-gpu","linux-gpu"),required=True); q.add_argument("--preion-maxwarn",type=int,default=0); q.add_argument("--preion-warning-rationale"); q.add_argument("--output",type=Path,required=True)
    e=sub.add_parser("assemble"); e.add_argument("--plan",type=Path,required=True); e.add_argument("--system-plan",type=Path,required=True); e.add_argument("--protein-preparation",type=Path,required=True); e.add_argument("--alignment-report",type=Path,required=True); e.add_argument("--ligand-topology",type=Path,required=True); e.add_argument("--ions-mdp",type=Path,required=True); e.add_argument("--em-mdp",type=Path,required=True); e.add_argument("--output",type=Path,required=True)
    v=sub.add_parser("verify"); v.add_argument("--receipt",type=Path,required=True)
    a=p.parse_args()
    try:
        if a.cmd=="plan":
            data=build_plan(a); write(a.output,data); print(f"Success! Data written to: {a.output}")
        elif a.cmd=="assemble": execute(a)
        else: verify(a)
    except AssemblyError as exc: print(f"Error: {exc}",file=sys.stderr); raise SystemExit(1)
if __name__=="__main__": main()
