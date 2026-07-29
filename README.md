# AI4S Workbench

Public, release-ready AI4S agent plugins maintained by
[Frankkk1912](https://github.com/Frankkk1912). This repository intentionally
contains only distributable workbenches; private research data, personal
memory, experimental workflows, and machine-specific configuration are not
included.

## Plugins

- [`molecular-modeling-workbench`](plugins/molecular-modeling-workbench/) —
  auditable docking-to-MD workflows for a WSL2-first public beta.

## Quick start

Clone this repository in your WSL2 Linux home directory, then follow the
plugin's README. The public plugin includes both `source-skills/` and its
generated `skills/` bundle, so `npm run sync`, `npm run check`, and `npm test`
can run from a clean checkout.

Scientific tools such as GNINA, Vina, GROMACS, ACPYPE, ChimeraX, and PyMOL are
not downloaded automatically. Run the environment audit and retain its receipt
before starting a scientific workflow.
