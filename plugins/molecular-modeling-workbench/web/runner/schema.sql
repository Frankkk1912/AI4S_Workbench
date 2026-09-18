-- M1 (T1.1): SQLite is the single authority for run/attempt/container
-- lifecycle state. Scientific artifacts (plans, manifests, receipts) remain
-- file + sha256 authoritative; the database stores references and
-- verification values only, never scientific conclusions.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    project TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    work_dir TEXT NOT NULL,
    manifest_path TEXT,
    stage_plan_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id INTEGER NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'container',
    container_name TEXT NOT NULL,
    cid_file TEXT,
    image_digest TEXT,
    work_dir TEXT NOT NULL,
    work_dir_hash TEXT,
    command_hash TEXT,
    ownership_labels TEXT,
    intent_at TEXT NOT NULL,
    container_at TEXT,
    finished_at TEXT,
    returncode INTEGER,
    receipt_path TEXT,
    boot_id TEXT NOT NULL,
    PRIMARY KEY (run_id, stage, attempt_id)
);

CREATE TABLE IF NOT EXISTS containers (
    container_id TEXT PRIMARY KEY,
    attempt_id INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    name TEXT NOT NULL,
    image_digest TEXT,
    labels TEXT,
    state TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    FOREIGN KEY (run_id, stage, attempt_id)
        REFERENCES attempts(run_id, stage, attempt_id)
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT,
    kind TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    sidecar_path TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    lineage TEXT
);

CREATE TABLE IF NOT EXISTS receipt_lineage (
    receipt_sha256 TEXT PRIMARY KEY,
    previous_sha256 TEXT,
    receipt_path TEXT NOT NULL,
    verified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_sessions (
    session_id TEXT PRIMARY KEY,
    run_id TEXT,
    stage TEXT,
    status TEXT NOT NULL,
    params TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    event TEXT NOT NULL,
    subject TEXT,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_work_dir ON runs(work_dir);
CREATE INDEX IF NOT EXISTS idx_attempts_run ON attempts(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_subject ON audit_log(subject);
