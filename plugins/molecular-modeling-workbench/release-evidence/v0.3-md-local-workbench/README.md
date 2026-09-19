# v0.3.0 local MD workbench acceptance index

This directory contains only public-safe acceptance metadata. It contains no
structures, trajectories, raw simulation logs, credentials, access tokens,
hostnames, or absolute workstation paths.

## Automated evidence

| Gate | Evidence | Result |
| --- | --- | --- |
| Web CI (V15) | [Molecular modeling workbench CI run 35418680922](https://github.com/Frankkk1912/AI4S_Workbench/actions/runs/35418680922) | `web-tests`: success; `cpu-contract`: success |
| Crash/concurrency/rollback drills (V1/V3/V7/V8/V12/V18) | `web/runner/tests/test_drills.py`; run through `npm run test:all` | Eight mock-only drills cover concurrent idempotency, runner exclusion, crash-window adoption, restart reconnection, boot-change fail-closed behavior, hash/parameter tamper rejection, the seven-day receipt boundary, and repeatable rollback ordering. |
| Full public test aggregate | `npm run test:all` | Pass: 20 Node contract tests (16 pass, 4 platform skips), scientific suites (30/7/15/5/4/16/38/8/15), runner 81, backend 58, and frontend 31. |
| Plugin assembly/version consistency | `npm run sync && npm run check` | Pass: package, plugin metadata, generated manifests, bundle, and all 12 skills are synchronized at `0.3.0`. |

The drill suite uses a fake Docker executable and never contacts a Docker
daemon or GPU. A passing mock suite does not constitute GPU evidence.

## Manual GPU gate (V17)

**Pending user execution (V17); no GPU checkpoint, restart, recovery, stop, or
continuation behavior is claimed for v0.3.0 until this gate is completed.**

The private evidence run must cover a small real GPU simulation continuing
across browser/Agent closure, service restart reconnection without duplicate
launch, host-restart interruption, user-approved checkpoint recovery with
`gmx check`, SIGTERM/grace checkpoint validation, and a frozen-checkpoint
`convert-tpr` continuation. Only a sanitized conclusion may be added here;
raw scientific files and local machine details remain outside the repository.

## Release boundary

This evidence index does not publish a release, mark the Draft PR ready, merge
it, or invoke release automation. Those remain explicit user decisions after
V17 and all automated gates pass.
