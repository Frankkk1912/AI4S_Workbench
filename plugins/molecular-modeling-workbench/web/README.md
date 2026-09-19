# Local MD workbench web services

The web stack is a single-user service bound to `127.0.0.1`. It does not grant
remote access and does not replace the scientific artifact/hash authority.

## Data directory and security

By default, runtime state is stored below the selected workspace at
`.ai4s-md-workbench/`:

- `runner.db` — SQLite lifecycle authority and audit log;
- `access.token` — local access credential, created with mode `0600`;
- `logs/` — service logs;
- `evidence/` — user-owned operational evidence.

Use `--data-dir` to select another user-owned location. The directory is mode
`0700`; do not place it in a shared or synchronized folder. Database migrations
are additive, idempotent, and verify `schema_version` after each startup.

Production serves `frontend/dist` from the API origin; build it first with
`npm ci --prefix web/frontend && npm --prefix web/frontend run build`. Enter the startup token
once; the handoff exchanges it for an HttpOnly, SameSite=Strict cookie so native
EventSource can authenticate without putting a secret in a URL. Host, Origin,
CSRF, path, and token checks remain enabled for API routes.

## User services

Example systemd user units live in `web/deploy/`. Review their workspace and
checkout paths before installing them under `~/.config/systemd/user/`. Lifecycle
commands use only `systemctl --user`:

```bash
uv run --project web --locked python -m web.runner.cli start
uv run --project web --locked python -m web.runner.cli status
uv run --project web --locked python -m web.runner.cli diagnose \
  --data-dir "$WORKSPACE/.ai4s-md-workbench"
uv run --project web --locked python -m web.runner.cli stop
```

No command uses `sudo` or starts a service during installation/tests. A user
service is not guaranteed to survive logout: the CLI reports the current linger
state and warns when it is disabled. Enabling linger is a separate workstation
owner decision. Shutting down the machine always stops these services.
