# Web test fixture contract

The web suites use standard-library `unittest`; no GPU, Docker daemon, network,
or running service is required.

- `web.runner.tests.helpers.make_db` creates a temporary migrated SQLite DB.
- `write_manifest` and `write_stage_plan` create minimal scientific references.
- `load_mock_docker` reuses the audited source-skill mock Docker adapter.
- `web.backend.tests.helpers.make_client` creates an in-process FastAPI
  `TestClient`, temporary workspace, and temporary runner DB.
- Frontend tests use Vitest/jsdom and mocked fetch/EventSource boundaries.

Fixtures must remain temporary, deterministic, and secret-free. Real GROMACS
CPU correctness fixtures are intentionally separate under
`source-skills/md-trajectory-analysis/tests/test_diagnostics_gmx.py`; they must
never be represented by the mock suite.

Unified no-GPU entry:

```bash
npm run test:all
```

`test:all` includes deferred skill suites and web backend/runner/frontend tests.
CI may invoke the web-only entry after installing frontend dependencies:

```bash
npm run test:web
```
