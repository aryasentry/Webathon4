-- ============================================================================
-- UGIE Database Migration — Initial Schema
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ============================================================================

-- Extension for UUID primary keys
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── users ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ugie_users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    github_id           BIGINT UNIQUE NOT NULL,
    login               TEXT NOT NULL,
    email               TEXT,
    avatar_url          TEXT,
    -- Encrypted GitHub access token (Fernet)
    encrypted_token     TEXT,
    token_scopes        TEXT[],
    token_valid         BOOLEAN DEFAULT TRUE,
    token_checked_at    TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ugie_users_github_id ON ugie_users(github_id);

-- ─── repositories ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ugie_repositories (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES ugie_users(id) ON DELETE CASCADE,
    github_id           BIGINT NOT NULL,
    owner_login         TEXT NOT NULL,
    name                TEXT NOT NULL,
    full_name           TEXT NOT NULL,
    private             BOOLEAN NOT NULL DEFAULT FALSE,
    archived            BOOLEAN NOT NULL DEFAULT FALSE,
    default_branch      TEXT NOT NULL DEFAULT 'main',
    language            TEXT,
    stargazers_count    INT NOT NULL DEFAULT 0,
    forks_count         INT NOT NULL DEFAULT 0,
    open_issues_count   INT NOT NULL DEFAULT 0,
    -- Role this user holds on the repo
    role                TEXT NOT NULL DEFAULT 'collaborator',
    -- Webhook management
    webhook_id          BIGINT,
    webhook_active      BOOLEAN DEFAULT FALSE,
    -- Sync state
    last_synced_at      TIMESTAMPTZ,
    backfill_cursor     TEXT,    -- commit SHA where backfill last stopped (for resumption)
    backfill_complete   BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(user_id, github_id)
);

CREATE INDEX IF NOT EXISTS idx_ugie_repos_user_id    ON ugie_repositories(user_id);
CREATE INDEX IF NOT EXISTS idx_ugie_repos_full_name  ON ugie_repositories(full_name);

-- ─── commits ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ugie_commits (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id             UUID NOT NULL REFERENCES ugie_repositories(id) ON DELETE CASCADE,
    sha                 TEXT NOT NULL,
    message             TEXT NOT NULL,
    author_login        TEXT,
    author_email        TEXT,
    authored_at         TIMESTAMPTZ NOT NULL,
    additions           INT NOT NULL DEFAULT 0,
    deletions           INT NOT NULL DEFAULT 0,
    files_changed       INT NOT NULL DEFAULT 0,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source              TEXT NOT NULL DEFAULT 'backfill',  -- 'backfill' | 'webhook'

    -- Idempotency key — safe to re-ingest from webhook + backfill
    UNIQUE(repo_id, sha)
);

CREATE INDEX IF NOT EXISTS idx_ugie_commits_repo_id     ON ugie_commits(repo_id);
CREATE INDEX IF NOT EXISTS idx_ugie_commits_authored_at ON ugie_commits(authored_at DESC);
CREATE INDEX IF NOT EXISTS idx_ugie_commits_author      ON ugie_commits(author_login);

-- ─── issues ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ugie_issues (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id             UUID NOT NULL REFERENCES ugie_repositories(id) ON DELETE CASCADE,
    number              INT NOT NULL,
    title               TEXT NOT NULL,
    state               TEXT NOT NULL,
    author_login        TEXT,
    assignee_login      TEXT,
    comments_count      INT NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL,
    closed_at           TIMESTAMPTZ,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(repo_id, number)
);

CREATE INDEX IF NOT EXISTS idx_ugie_issues_repo_id ON ugie_issues(repo_id);
CREATE INDEX IF NOT EXISTS idx_ugie_issues_state ON ugie_issues(state);

-- ─── pull_requests ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ugie_pull_requests (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id             UUID NOT NULL REFERENCES ugie_repositories(id) ON DELETE CASCADE,
    number              INT NOT NULL,
    title               TEXT NOT NULL,
    state               TEXT NOT NULL,
    author_login        TEXT,
    merged              BOOLEAN NOT NULL DEFAULT FALSE,
    additions           INT NOT NULL DEFAULT 0,
    deletions           INT NOT NULL DEFAULT 0,
    changed_files       INT NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL,
    closed_at           TIMESTAMPTZ,
    merged_at           TIMESTAMPTZ,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(repo_id, number)
);

CREATE INDEX IF NOT EXISTS idx_ugie_pull_requests_repo_id ON ugie_pull_requests(repo_id);
CREATE INDEX IF NOT EXISTS idx_ugie_pull_requests_state ON ugie_pull_requests(state);

-- ─── contribution_snapshots ───────────────────────────────────────────────────
-- Pre-aggregated daily metrics (O(1) analytics queries)
CREATE TABLE IF NOT EXISTS ugie_contribution_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES ugie_users(id) ON DELETE CASCADE,
    repo_id         UUID NOT NULL REFERENCES ugie_repositories(id) ON DELETE CASCADE,
    snapshot_date   DATE NOT NULL,
    commit_count    INT NOT NULL DEFAULT 0,
    additions       INT NOT NULL DEFAULT 0,
    deletions       INT NOT NULL DEFAULT 0,
    files_changed   INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(user_id, repo_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_ugie_snapshots_user_repo
    ON ugie_contribution_snapshots(user_id, repo_id);
CREATE INDEX IF NOT EXISTS idx_ugie_snapshots_date
    ON ugie_contribution_snapshots(snapshot_date DESC);

-- ─── webhook_events ───────────────────────────────────────────────────────────
-- Raw event store — used for replay protection and the dead-letter queue
CREATE TABLE IF NOT EXISTS ugie_webhook_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- GitHub-provided delivery ID (X-GitHub-Delivery header)
    event_id        TEXT UNIQUE NOT NULL,
    event_type      TEXT NOT NULL,
    repo_id         UUID REFERENCES ugie_repositories(id) ON DELETE SET NULL,
    raw_payload     JSONB NOT NULL,
    processed       BOOLEAN NOT NULL DEFAULT FALSE,
    failed          BOOLEAN NOT NULL DEFAULT FALSE,
    retry_count     INT NOT NULL DEFAULT 0,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_ugie_webhook_events_event_id  ON ugie_webhook_events(event_id);
CREATE INDEX IF NOT EXISTS idx_ugie_webhook_events_processed ON ugie_webhook_events(processed);
CREATE INDEX IF NOT EXISTS idx_ugie_webhook_events_failed    ON ugie_webhook_events(failed);

-- ─── tasks ────────────────────────────────────────────────────────────────────
-- AI-created and manually-created project tasks
CREATE TABLE IF NOT EXISTS ugie_tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES ugie_users(id) ON DELETE SET NULL,
    repo_id             UUID REFERENCES ugie_repositories(id) ON DELETE CASCADE,
    -- Stores the frontend localStorage project UUID so tasks survive without a linked repo
    frontend_project_id TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT,
    assignee            TEXT,                -- GitHub login or display name
    priority            TEXT NOT NULL DEFAULT 'medium',  -- low | medium | high | critical
    deadline            DATE,
    tags                TEXT[] DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'todo',    -- todo | in-progress | done
    story_points        INT NOT NULL DEFAULT 1,
    created_by          TEXT,               -- GitHub login of the creator
    source              TEXT NOT NULL DEFAULT 'manual',  -- manual | ai
    -- Calendar: the day this task is planned/scheduled for (NULL = unscheduled)
    scheduled_date      DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ugie_tasks_user_id     ON ugie_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_ugie_tasks_project     ON ugie_tasks(frontend_project_id);
CREATE INDEX IF NOT EXISTS idx_ugie_tasks_repo_id     ON ugie_tasks(repo_id);
CREATE INDEX IF NOT EXISTS idx_ugie_tasks_status      ON ugie_tasks(status);
CREATE INDEX IF NOT EXISTS idx_ugie_tasks_scheduled   ON ugie_tasks(scheduled_date) WHERE scheduled_date IS NOT NULL;

-- Migration: add scheduled_date to existing deployments (safe to run multiple times)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='ugie_tasks' AND column_name='scheduled_date'
    ) THEN
        ALTER TABLE ugie_tasks ADD COLUMN scheduled_date DATE;
        CREATE INDEX IF NOT EXISTS idx_ugie_tasks_scheduled
            ON ugie_tasks(scheduled_date) WHERE scheduled_date IS NOT NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_ugie_tasks_updated_at'
    ) THEN
        CREATE TRIGGER trg_ugie_tasks_updated_at
        BEFORE UPDATE ON ugie_tasks
        FOR EACH ROW EXECUTE FUNCTION ugie_set_updated_at();
    END IF;
END $$;

-- ─── health ping table (used by DB connectivity check) ───────────────────────
CREATE TABLE IF NOT EXISTS ugie_health_ping (
    id SERIAL PRIMARY KEY
);
INSERT INTO ugie_health_ping(id) VALUES (1) ON CONFLICT DO NOTHING;

-- ─── updated_at trigger function ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION ugie_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'ugie_users',
        'ugie_repositories',
        'ugie_contribution_snapshots',
        'ugie_issues',
        'ugie_pull_requests'
    ]
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_%s_updated_at ON %s;
             CREATE TRIGGER trg_%s_updated_at
             BEFORE UPDATE ON %s
             FOR EACH ROW EXECUTE FUNCTION ugie_set_updated_at();',
            t, t, t, t
        );
    END LOOP;
END $$;

-- ─── ugie_github_identities ───────────────────────────────────────────────────
-- Universal registry: maps any GitHub username seen in the system to a
-- UGIE site user (ugie_users) if they have ever logged in.
CREATE TABLE IF NOT EXISTS ugie_github_identities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    github_login    TEXT UNIQUE NOT NULL,
    github_id       BIGINT UNIQUE,                  -- numeric GitHub user ID
    avatar_url      TEXT,
    name            TEXT,                           -- GitHub display name
    bio             TEXT,
    company         TEXT,
    location        TEXT,
    -- Link to the UGIE registered user (NULL = not yet signed up)
    site_user_id    UUID REFERENCES ugie_users(id) ON DELETE SET NULL,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ                     -- when site_user_id was confirmed
);

CREATE INDEX IF NOT EXISTS idx_ugie_github_identities_login
    ON ugie_github_identities(github_login);
CREATE INDEX IF NOT EXISTS idx_ugie_github_identities_github_id
    ON ugie_github_identities(github_id) WHERE github_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ugie_github_identities_site_user
    ON ugie_github_identities(site_user_id) WHERE site_user_id IS NOT NULL;


-- ─── ugie_repo_collaborators ──────────────────────────────────────────────────
-- Records each GitHub user who has explicit collaborator access to a tracked repo.
CREATE TABLE IF NOT EXISTS ugie_repo_collaborators (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id             UUID NOT NULL REFERENCES ugie_repositories(id) ON DELETE CASCADE,
    github_identity_id  UUID NOT NULL REFERENCES ugie_github_identities(id) ON DELETE CASCADE,
    -- GitHub permission level: read | triage | write | maintain | admin
    permission          TEXT NOT NULL DEFAULT 'read',
    role_name           TEXT,                       -- GitHub verbose role name
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(repo_id, github_identity_id)
);

CREATE INDEX IF NOT EXISTS idx_ugie_repo_collaborators_repo_id
    ON ugie_repo_collaborators(repo_id);
CREATE INDEX IF NOT EXISTS idx_ugie_repo_collaborators_identity
    ON ugie_repo_collaborators(github_identity_id);
