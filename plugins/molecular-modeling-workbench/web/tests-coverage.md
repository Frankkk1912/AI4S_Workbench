# Web validation coverage (M6 T6.3)

This inventory maps the plan validation contract to executable evidence. Test
counts are reported by the command output, not hard-coded here.

| Contract | Evidence |
| --- | --- |
| V1 container ownership/reconcile | `web/runner/tests/test_submission.py`, `test_reconcile.py` |
| V2 finalize closure | `web/runner/tests/test_finalize.py` |
| V3 idempotency/concurrency | `web/runner/tests/test_submission.py` |
| V4 local API security | `web/backend/tests/test_security.py`, `test_paths.py`, `test_runs.py` |
| V5 approval/advance | `web/backend/tests/test_approvals.py`, `web/runner/tests/test_orchestrator.py` |
| V6 stop/resume/extend | `web/runner/tests/test_lifecycle.py`, source `test_extend_contract.py` |
| V7 receipt boundary | `web/backend/tests/test_receipt_boundary.py` |
| V8 boot restart | `web/runner/tests/test_db.py`, `test_reconcile.py` |
| V9 frontend semantics | `web/frontend/src/components/*.test.tsx` |
| V10 real analysis correctness | `source-skills/md-trajectory-analysis/tests/test_diagnostics_gmx.py` (real CPU gmx), `test_diagnostics.py` (mock rejection) |
| V11 analysis admission/style/export | `web/backend/tests/test_analysis.py`, `web/runner/tests/test_analysis_runner.py`, `source-skills/md-simulation-plotting/tests/`, `AnalysisGallery.test.tsx` |
| V12 tamper/hash gates | source `test_grompp_contract.py`, runner submission/analysis tests |
| V13 platform regression | `npm run check`, `npm test` |
| V14 lifecycle/deployment/migration | `web/runner/tests/test_cli.py`, `test_migrate.py`, `web/backend/tests/test_token_handoff.py` |
| V15 CI wiring | `.github/workflows/ci.yml` `web-tests` job; only a real PR run may establish green CI evidence |
| V16 evidence gates | Plan/changelog evidence; not replaced by a unit test |
| V17 real GPU E2E | M7 manual test; not claimed by M6 |
| V18 rollback drill | M7 `test_drills.py`; not claimed by M6 |

## Commands

```bash
npm run check
npm test
npm run test:all
uv run --project web --locked python -m unittest discover -s web/runner/tests -t .
uv run --project web --locked python -m unittest discover -s web/backend/tests -t .
npm --prefix web/frontend run build
npm --prefix web/frontend run lint
npm --prefix web/frontend test -- --run
```

The first PR execution of `web-tests` remains external evidence; local success
must not be described as a green GitHub Actions run.
