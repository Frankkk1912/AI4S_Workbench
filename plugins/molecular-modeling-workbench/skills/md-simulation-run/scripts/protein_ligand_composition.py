#!/usr/bin/env python3
"""Compose reviewed protein and pose-aligned ligand files into a GROMACS work directory."""
from __future__ import annotations
import argparse, hashlib, json, shutil, sys
from pathlib import Path

class CompositionError(ValueError): pass
def load(path):
    try: return json.loads(Path(path).read_text())
    except Exception as e: raise CompositionError(f"Cannot read {path}: {e}")
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def ref(value, label):
    if not isinstance(value, dict) or not isinstance(value.get('path'), str) or not isinstance(value.get('sha256'), str): raise CompositionError(f"{label} reference is incomplete.")
    path=Path(value['path'])
    if not path.is_file() or sha(path)!=value['sha256']: raise CompositionError(f"{label} is missing or changed.")
    return path.resolve()
def gro(path):
    rows=Path(path).read_text().splitlines()
    try: n=int(rows[1])
    except Exception: raise CompositionError(f"Invalid GRO atom count: {path}")
    if len(rows)<n+3: raise CompositionError(f"Incomplete GRO file: {path}")
    return rows[0], rows[2:2+n], rows[2+n]
def write(path,data): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data,indent=2)+'\n')
def main():
 p=argparse.ArgumentParser(description=__doc__); p.add_argument('--protein-preparation',type=Path,required=True); p.add_argument('--alignment-report',type=Path,required=True); p.add_argument('--ligand-topology',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
 try:
  protein=load(a.protein_preparation); align=load(a.alignment_report)
  if protein.get('artifact_type')!='reviewed_protein_preparation' or protein.get('status')!='reviewed': raise CompositionError('Reviewed protein preparation is required.')
  protein_top=ref(protein.get('protein_topology'),'protein topology'); protein_gro=ref(protein.get('protein_coordinates'),'protein coordinates'); ligand_gro=ref(align.get('coordinates'),'pose-aligned ligand coordinates'); ligand_itp=a.ligand_topology.resolve()
  if not ligand_itp.is_file() or ligand_itp.stat().st_size==0: raise CompositionError('Ligand topology is missing or empty.')
 except CompositionError as e: print(f'Error: {e}',file=sys.stderr); raise SystemExit(1)
 if align.get('heavy_atom_rmsd_nm',1)>0.01: print('Error: Pose alignment RMSD exceeds 0.01 nm.',file=sys.stderr); raise SystemExit(1)
 out=a.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True)
 for item in protein_top.parent.iterdir():
  if item.is_file(): shutil.copy2(item,out/item.name)
 ligand_text=ligand_itp.read_text(); atomtypes='[ atomtypes ]'
 if atomtypes not in ligand_text or '[ moleculetype ]' not in ligand_text: print('Error: Ligand topology lacks required atomtypes/moleculetype sections.',file=sys.stderr); raise SystemExit(1)
 prefix, remainder=ligand_text.split(atomtypes,1); atomtype_body, ligand_body=remainder.split('[ moleculetype ]',1)
 (out/'BNZ_atomtypes.itp').write_text(atomtypes+atomtype_body)
 (out/'BNZ.itp').write_text(prefix+'[ moleculetype ]'+ligand_body)
 top=(out/protein_top.name).read_text(); marker='[ system ]'; forcefield='#include "amber99sb-ildn.ff/forcefield.itp"'
 if marker not in top: print('Error: Protein topology lacks [ system ].',file=sys.stderr); raise SystemExit(1)
 if forcefield not in top: print('Error: Protein topology lacks the expected AMBER force-field include.',file=sys.stderr); raise SystemExit(1)
 top=top.replace(forcefield,forcefield+'\n#include "BNZ_atomtypes.itp"',1)
 top=top.replace(marker,'#include "BNZ.itp"\n\n'+marker,1)
 if '[ molecules ]' not in top: print('Error: Protein topology lacks [ molecules ].',file=sys.stderr); raise SystemExit(1)
 top=top.rstrip()+'\nBNZ                 1\n'; (out/'topol.top').write_text(top)
 _,pa,box=gro(protein_gro); _,la,_=gro(ligand_gro); (out/'complex.gro').write_text('Protein-ligand complex\n'+str(len(pa)+len(la))+'\n'+'\n'.join(pa+la)+'\n'+box+'\n')
 data={'schema_version':'1.0','artifact_type':'protein_ligand_composition','protein_preparation':{'path':str(a.protein_preparation.resolve()),'sha256':sha(a.protein_preparation)},'alignment_report':{'path':str(a.alignment_report.resolve()),'sha256':sha(a.alignment_report)},'artifacts':{'topology':{'path':str((out/'topol.top').resolve()),'sha256':sha(out/'topol.top')},'coordinates':{'path':str((out/'complex.gro').resolve()),'sha256':sha(out/'complex.gro')}},'status':'composed','scope':'Topology and coordinates are composed only; box, solvent, ions, and em.tpr are not yet generated.'}; write(a.output,data); print(f'Success! Data written to: {a.output}')
if __name__=='__main__': main()
