"""Read-only protected parameters and parameter read/diff router (M2 T2.6).

Defaults originate from the `md-simulation-run/SKILL.md` MDP templates and the
handoff/manifest fields. Prepared force field, water model, and topology
metadata are protected: this API exposes them read-only and rejects any
modification with an explicit reason (changing them requires re-preparing the
system / handoff, per R5). The read/diff responses carry `default`, `current`,
`source`, and `explanation` so the UI can render an explanatory review.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from ..paths import PathEscapeError, PathNotFoundError, resolve_workspace_path
from ..security import require_local_request, require_token

router = APIRouter(
    prefix="/params",
    tags=["params"],
    dependencies=[Depends(require_token), Depends(require_local_request)],
)

# Default MDP templates transcribed from md-simulation-run/SKILL.md
# "Standard GROMACS Parameters (.mdp files)". Values are the literal template
# strings so a diff is a plain string comparison against the prepared file.
MDP_DEFAULTS: dict[str, dict[str, str]] = {
    "em": {
        "integrator": "steep",
        "emtol": "1000.0",
        "emstep": "0.01",
        "nsteps": "50000",
        "nstlist": "1",
        "cutoff-scheme": "Verlet",
        "ns_type": "grid",
        "coulombtype": "PME",
        "rcoulomb": "1.2",
        "rvdw": "1.2",
        "pbc": "xyz",
    },
    "nvt": {
        "define": "-DPOSRES",
        "integrator": "md",
        "nsteps": "50000",
        "dt": "0.002",
        "nstxout": "5000",
        "nstlog": "5000",
        "nstenergy": "5000",
        "continuation": "no",
        "constraint_algorithm": "lincs",
        "constraints": "h-bonds",
        "lincs_iter": "1",
        "lincs_order": "4",
        "nstlist": "20",
        "cutoff-scheme": "Verlet",
        "ns_type": "grid",
        "coulombtype": "PME",
        "rcoulomb": "1.2",
        "rvdw": "1.2",
        "pbc": "xyz",
        "tcoupl": "V-rescale",
        "tc-grps": "Protein Non-Protein",
        "tau_t": "0.1 0.1",
        "ref_t": "310 310",
        "gen_vel": "yes",
        "gen_temp": "310",
        "gen_seed": "-1",
    },
    "npt": {
        "define": "-DPOSRES",
        "integrator": "md",
        "nsteps": "50000",
        "dt": "0.002",
        "nstxout": "5000",
        "nstlog": "5000",
        "nstenergy": "5000",
        "continuation": "yes",
        "constraint_algorithm": "lincs",
        "constraints": "h-bonds",
        "lincs_iter": "1",
        "lincs_order": "4",
        "nstlist": "20",
        "cutoff-scheme": "Verlet",
        "ns_type": "grid",
        "coulombtype": "PME",
        "rcoulomb": "1.2",
        "rvdw": "1.2",
        "pbc": "xyz",
        "tcoupl": "V-rescale",
        "tc-grps": "Protein Non-Protein",
        "tau_t": "0.1 0.1",
        "ref_t": "310 310",
        "pcoupl": "C-rescale",
        "pcoupltype": "isotropic",
        "tau_p": "2.0",
        "ref_p": "1.0",
        "compressibility": "4.5e-5",
        "refcoord_scaling": "com",
    },
    "md_prod": {
        "integrator": "md",
        "nsteps": "50000000",
        "dt": "0.002",
        "nstxout-compressed": "25000",
        "nstlog": "25000",
        "nstenergy": "25000",
        "continuation": "yes",
        "constraint_algorithm": "lincs",
        "constraints": "h-bonds",
        "lincs_iter": "1",
        "lincs_order": "4",
        "nstlist": "20",
        "cutoff-scheme": "Verlet",
        "ns_type": "grid",
        "coulombtype": "PME",
        "rcoulomb": "1.2",
        "rvdw": "1.2",
        "pbc": "xyz",
        "DispCorr": "EnerPres",
        "tcoupl": "V-rescale",
        "tc-grps": "Protein Non-Protein",
        "tau_t": "0.1 0.1",
        "ref_t": "310 310",
        "pcoupl": "C-rescale",
        "pcoupltype": "isotropic",
        "tau_p": "2.0",
        "ref_p": "1.0",
        "compressibility": "4.5e-5",
    },
}

FORCE_FIELD_DEFAULTS = {
    "primary": "CHARMM36",
    "primary_variant": "charmm36-jul2022.ff",
    "fallback": ["AMBER99SB-ILDN", "AMBER ff14SB"],
    "ligand": {"amber-gaff": "amber", "charmm-cgenff": "charmm"},
    "source": "md-simulation-run/SKILL.md: Force Field Recommendation",
}

WATER_MODEL_DEFAULT = {
    "model": "TIP3P",
    "gmx_flag": "tip3p",
    "source": "md-simulation-run/SKILL.md: pdb2gmx -water tip3p",
}

PROTECTED_FIELDS = ("force_field", "water_model", "topology")
WATER_MODEL_MARKERS = {
    "tip3p": "TIP3P",
    "spc": "SPC",
    "spce": "SPC/E",
    "tip4p": "TIP4P",
    "tip4pew": "TIP4P-Ew",
    "tip5p": "TIP5P",
}


def parse_mdp(path: Path) -> dict[str, str]:
    """Read a GROMACS .mdp file into key -> raw-value strings (comments stripped)."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


def detect_water_model(topology: Path) -> str | None:
    """Detect a known water model include from a prepared topology file."""
    text = topology.read_text(encoding="utf-8", errors="replace")
    for marker, name in WATER_MODEL_MARKERS.items():
        if f'"{marker}.itp"' in text or f"{marker}.itp" in text:
            return name
    return None


def _resolve(roots: list[str], value: str, label: str, must_exist: bool = True) -> Path:
    try:
        return resolve_workspace_path(roots, value, label=label, must_exist=must_exist)
    except (PathEscapeError, PathNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _read_json(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"cannot read {label}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=f"{label} must be a JSON object")
    return data


def _protected_snapshot(
    roots: list[str], handoff_path: str | None, topology_path: str | None
) -> dict:
    """Read the protected (read-only) scientific metadata from handoff/topology."""
    force_field = {
        "default": FORCE_FIELD_DEFAULTS["primary"],
        "current": None,
        "source": FORCE_FIELD_DEFAULTS["source"],
        "protected": True,
        "explanation": (
            "Prepared protein force field is read-only; changing it requires "
            "re-preparing the system / handoff."
        ),
    }
    water_model = {
        "default": WATER_MODEL_DEFAULT["model"],
        "current": None,
        "source": WATER_MODEL_DEFAULT["source"],
        "protected": True,
        "explanation": (
            "Prepared water model is read-only; changing it requires re-preparing "
            "the system / handoff."
        ),
    }
    topology = {
        "current": None,
        "source": "docking_to_md_handoff ligand.topology",
        "protected": True,
        "explanation": (
            "Prepared topology metadata is read-only; changing it requires "
            "re-preparing the system / handoff."
        ),
    }

    if handoff_path:
        handoff = _read_json(_resolve(roots, handoff_path, "handoff"), "handoff")
        ligand = handoff.get("ligand") or {}
        if isinstance(ligand, dict):
            if ligand.get("force_field"):
                force_field["current"] = ligand["force_field"]
            if ligand.get("protein_force_field"):
                force_field["current"] = (
                    f"{ligand['protein_force_field']} (ligand {ligand.get('force_field')})"
                    if ligand.get("force_field")
                    else ligand["protein_force_field"]
                )
            topo_ref = ligand.get("topology")
            if isinstance(topo_ref, dict) and isinstance(topo_ref.get("path"), str):
                topology["current"] = topo_ref

    if topology_path:
        resolved_topology = _resolve(roots, topology_path, "topology")
        topology["current"] = {"path": str(resolved_topology)}
        detected = detect_water_model(resolved_topology)
        if detected:
            water_model["current"] = detected

    return {
        "force_field": force_field,
        "water_model": water_model,
        "topology": topology,
    }


@router.get("/defaults")
def get_defaults() -> dict:
    return {
        "mdp": {
            stage: {
                "parameters": values,
                "source": "md-simulation-run/SKILL.md: Standard GROMACS Parameters (.mdp files)",
            }
            for stage, values in MDP_DEFAULTS.items()
        },
        "force_field": FORCE_FIELD_DEFAULTS,
        "water_model": WATER_MODEL_DEFAULT,
        "protected_fields": list(PROTECTED_FIELDS),
    }


@router.get("/diff")
def get_diff(
    request: Request,
    handoff_path: str | None = None,
    topology_path: str | None = None,
    mdp_path: str | None = None,
    stage: str | None = None,
) -> dict:
    roots = request.app.state.workspace_roots
    protected = _protected_snapshot(roots, handoff_path, topology_path)

    mdp_diff: list[dict] = []
    if mdp_path and stage:
        if stage not in MDP_DEFAULTS:
            raise HTTPException(status_code=400, detail=f"unknown stage: {stage}")
        current = parse_mdp(_resolve(roots, mdp_path, "mdp"))
        defaults = MDP_DEFAULTS[stage]
        for key, default in sorted(defaults.items()):
            value = current.get(key)
            mdp_diff.append(
                {
                    "key": key,
                    "default": default,
                    "current": value,
                    "changed": value != default,
                    "explanation": f"Default {stage}.mdp value from SKILL.md template.",
                    "protected": False,
                }
            )

    return {
        "mdp": mdp_diff,
        "force_field": protected["force_field"],
        "water_model": protected["water_model"],
        "topology": protected["topology"],
        "protected_fields": list(PROTECTED_FIELDS),
    }


@router.api_route("/{field:path}", methods=["PUT", "PATCH"])
def reject_protected_write(field: str) -> None:
    raise HTTPException(
        status_code=403,
        detail=(
            f"parameter field {field!r} is read-only; protected information "
            "(force field, water model, topology) requires re-preparing the "
            "system / handoff to change"
        ),
    )
