# v0.2.0 Windows 11 / WSL2 / RTX 3080 acceptance

This directory contains only a sanitized aggregate receipt for the v0.2.0
release gate. It contains no raw coordinates, trajectories, logs, credentials,
or absolute local paths.

## Accepted scope

- Windows 11 Pro build 26200; Ubuntu 22.04 WSL2; RTX 3080; Docker Desktop.
- WSL-native Codex CLI and Claude Code workbench-skill discovery.
- A receipt-gated public RCSB 181L + BNZ docking smoke.
- A separately reviewed, digest-pinned GPU MD smoke: EM, 100 ps NVT, 100 ps
  NPT, and 100 ps production at 300 K, 1 bar, and 2 fs.

See `technical_acceptance_receipt.json` for the machine-readable summary,
versions, contract outcomes, and residual risks.

## Interpretation boundary

The fixture is a technical connectivity test. Its docking scores, short MD
trajectory, and basic execution QC are not evidence of binding affinity, free
energy, convergence, stability, or biological validity.
