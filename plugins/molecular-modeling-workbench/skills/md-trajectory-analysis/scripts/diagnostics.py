#!/usr/bin/env python3
"""Parameterized diagnostics for the trajectory analysis skill (M5 T5.1).

Extends the existing basic pipeline with a `diagnostics` producer that:

- extracts temperature / pressure / potential-energy time series from a GROMACS
  energy file (`.edr`) via `gmx energy`;
- reuses the basic pipeline's PBC correction and RMSD/RMSF gmx invocations, but
  accepts an optional time window (`-b`/`-e`), an equilibration start (ns), and
  a *predefined* atom group (generated through `auto_index`, never a free
  selection expression).

Atom groups are constrained to the predefined set, so a free/arbitrary index
expression is refused instead of being passed to GROMACS. The module only
assembles and runs the audited `gmx` commands; the scientific parameters it
actually used are persisted alongside the outputs so downstream layers can
record them separately from plotting style (T5.3).
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from contextlib import suppress

from auto_index import generate_default_index, get_group_name
from basic_pipeline import run_gmx_cmd

# Predefined atom groups (mirrors auto_index.get_group_name). No free
# expressions are accepted here; an out-of-set name fails closed.
PREDEFINED_GROUPS = frozenset(
    {"protein", "backbone", "c-alpha", "non-protein", "water", "ions", "system"}
)

ENERGY_TERMS = ("Temperature", "Pressure", "Potential")

SUMMARY_SCHEMA_VERSION = "1.0"
SUMMARY_ARTIFACT_TYPE = "md_diagnostics_summary"


class DiagnosticsError(ValueError):
    """Raised when a diagnostics request must be refused."""


def validate_time_window(begin, end):
    """Refuse a negative or empty time window; return normalized floats."""
    if begin is None and end is None:
        return None, None
    b = None if begin is None else float(begin)
    e = None if end is None else float(end)
    if b is not None and b < 0:
        raise DiagnosticsError(f"begin time (-b) must be >= 0, got {b}")
    if e is not None and e < 0:
        raise DiagnosticsError(f"end time (-e) must be >= 0, got {e}")
    if b is not None and e is not None and b >= e:
        raise DiagnosticsError(f"begin ({b}) must be less than end ({e})")
    return b, e


def validate_group(group, fit_group=None):
    """Refuse a group outside the predefined set (no free expressions)."""
    name = (group or "backbone").lower()
    if name not in PREDEFINED_GROUPS:
        raise DiagnosticsError(
            f"group {group!r} is not a predefined atom group; "
            f"choose from {sorted(PREDEFINED_GROUPS)}"
        )
    fit = (fit_group or group).lower()
    if fit not in PREDEFINED_GROUPS:
        raise DiagnosticsError(
            f"fit group {fit_group!r} is not a predefined atom group; "
            f"choose from {sorted(PREDEFINED_GROUPS)}"
        )
    return name, fit


def _time_flags(begin, end):
    flags = []
    if begin is not None:
        flags += ["-b", str(begin)]
    if end is not None:
        flags += ["-e", str(end)]
    return flags


def normalize_energy_columns(path):
    """Rewrite gmx's internal term order to the public ENERGY_TERMS order."""
    source = str(path)
    with open(source, encoding="utf-8") as handle:
        lines = handle.readlines()
    legend_pattern = re.compile(r'^@\s+s(\d+)\s+legend\s+"([^"]+)"')
    legends = {}
    for line in lines:
        if match := legend_pattern.match(line.strip()):
            legends[match.group(2).casefold()] = int(match.group(1)) + 1
    try:
        columns = [legends[name.casefold()] for name in ENERGY_TERMS]
    except KeyError as exc:
        raise DiagnosticsError(
            f"gmx energy output is missing requested legend: {exc.args[0]}"
        ) from exc

    normalized = []
    inserted_legends = False
    for line in lines:
        stripped = line.strip()
        if legend_pattern.match(stripped):
            if not inserted_legends:
                normalized.extend(
                    f'@ s{index} legend "{name}"\n'
                    for index, name in enumerate(ENERGY_TERMS)
                )
                inserted_legends = True
            continue
        if stripped and not stripped.startswith(("#", "@")):
            values = stripped.split()
            if len(values) <= max(columns):
                raise DiagnosticsError("gmx energy output has too few numeric columns")
            line = " ".join([values[0], *(values[index] for index in columns)]) + "\n"
        normalized.append(line)

    fd, tmp = tempfile.mkstemp(
        dir=os.path.dirname(source), prefix="energy.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(normalized)
        os.replace(tmp, source)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


def run_energy(edr_file, outdir, begin=None, end=None):
    """Extract temperature/pressure/potential energy from `.edr` to `energy.xvg`."""
    out = os.path.join(outdir, "energy.xvg")
    if os.path.exists(out):
        return out
    cmd = ["gmx", "energy", "-f", str(edr_file), "-o", out] + _time_flags(begin, end)
    # Select the terms by name; the trailing blank line ends the interactive list.
    selection = "\n".join(ENERGY_TERMS) + "\n\n"
    run_gmx_cmd(cmd, selection)
    normalize_energy_columns(out)
    return out


def run_pbc_fit(tpr_file, xtc_file, outdir, index_file):
    """Reuse the basic pipeline PBC correction (center protein, output system)."""
    xtc_pbc = os.path.join(outdir, "md_fit.xtc")
    if os.path.exists(xtc_pbc):
        return xtc_pbc
    run_gmx_cmd(
        [
            "gmx",
            "trjconv",
            "-s",
            str(tpr_file),
            "-f",
            str(xtc_file),
            "-o",
            xtc_pbc,
            "-n",
            str(index_file),
            "-pbc",
            "mol",
            "-center",
        ],
        "Protein\nSystem\n",
    )
    return xtc_pbc


def run_rmsd(tpr_file, xtc_pbc, outdir, begin, end, group, fit_group, index_file):
    out = os.path.join(outdir, "rmsd.xvg")
    if os.path.exists(out):
        return out
    cmd = [
        "gmx",
        "rms",
        "-s",
        str(tpr_file),
        "-f",
        xtc_pbc,
        "-o",
        out,
        "-n",
        str(index_file),
        "-tu",
        "ns",
    ] + _time_flags(
        None if begin is None else begin / 1000.0,
        None if end is None else end / 1000.0,
    )
    run_gmx_cmd(cmd, f"{get_group_name(fit_group)}\n{get_group_name(group)}\n")
    return out


def run_rmsf(tpr_file, xtc_pbc, outdir, begin, end, group, index_file):
    out = os.path.join(outdir, "rmsf.xvg")
    if os.path.exists(out):
        return out
    cmd = [
        "gmx",
        "rmsf",
        "-s",
        str(tpr_file),
        "-f",
        xtc_pbc,
        "-o",
        out,
        "-n",
        str(index_file),
        "-res",
    ] + _time_flags(begin, end)
    run_gmx_cmd(cmd, f"{get_group_name(group)}\n")
    return out


def write_summary(outdir, summary):
    """Persist the scientific parameters actually used, for provenance (T5.3)."""
    path = os.path.join(outdir, "diagnostics_summary.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def run_diagnostics(
    tpr_file,
    xtc_file,
    edr_file,
    outdir="analysis_out",
    begin=None,
    end=None,
    eq_start=0.0,
    group="backbone",
    fit_group=None,
):
    """Run the parameterized diagnostics producer into a session directory."""
    os.makedirs(outdir, exist_ok=True)
    begin, end = validate_time_window(begin, end)
    group, fit = validate_group(group, fit_group)

    # Reuse auto_index group generation; the predefined group names are the
    # only accepted selection surface (no free expressions).
    index_file = generate_default_index(tpr_file, os.path.join(outdir, "analysis.ndx"))

    energy = run_energy(edr_file, outdir, begin, end)
    xtc_pbc = run_pbc_fit(tpr_file, xtc_file, outdir, index_file)
    rmsd = run_rmsd(tpr_file, xtc_pbc, outdir, begin, end, group, fit, index_file)
    rmsf = run_rmsf(tpr_file, xtc_pbc, outdir, begin, end, group, index_file)

    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "artifact_type": SUMMARY_ARTIFACT_TYPE,
        "tpr": str(tpr_file),
        "xtc": str(xtc_file),
        "edr": str(edr_file),
        "begin_ps": begin,
        "end_ps": end,
        "eq_start_ns": float(eq_start),
        "group": group,
        "fit_group": fit,
        "energy_terms": list(ENERGY_TERMS),
        "outputs": {
            "energy": os.path.basename(energy),
            "rmsd": os.path.basename(rmsd),
            "rmsf": os.path.basename(rmsf),
        },
    }
    write_summary(outdir, summary)
    print(f"Diagnostics complete. Summary and time series written to '{outdir}'")
    return summary


if __name__ == "__main__":
    # Standalone usage is intentionally minimal; the CLI entry point is
    # md_analyze_cli.py `diagnostics` (kept in the audited producer surface).
    print(
        "diagnostics is a library module; use md_analyze_cli.py diagnostics.",
        file=sys.stderr,
    )
    sys.exit(2)
