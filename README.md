# UGIE — Universal GitHub Intelligence Engine

> **Production-grade developer telemetry infrastructure, team collaboration tracker, and project intelligence layer — powered by GitHub OAuth + Supabase + Next.js.**

UGIE transforms raw GitHub repository activity into a structured, real-time behavioral model of team development velocity, coordination health, and integration readiness. It also maintains a canonical identity registry linking GitHub users to site accounts for consistent team views across commits, issues, PRs, and collaborator lists.

---

## ✨ Key Features

| Capability | Description |
|---|---|
| **GitHub Identity Federation** | OAuth flow, Fernet-encrypted token vault, scope verification |
| **Repository Graph Discovery** | Discovers owned, collaborator, org, and outside-collab repos |
| **Historical Backfill** | Cursor-resumable, rate-limit-aware commit + issue + PR ingestion |
| **Real-Time Webhook Streaming** | HMAC-verified, Redis-deduped, < 2s ACK per push/PR event |
| **Event Reliability Pipeline** | Retry, dead-letter, idempotent processors |
| **Intelligence Analytics** | Commit frequency, Shannon entropy, z-score burst detection |
| **Collaborator Ingestion** | Fetches GitHub repo collaborators, maps GitHub users → site users |
| **Team Activity View** | Per-contributor commit velocity, PR, and issue metrics |
| **Kanban Board** | Live sprint board from open issues + PRs |
| **Observability** | Structured JSON logs, in-process metrics, health endpoints |

---

## Architecture

```
                ┌────────────────────┐
                │   GitHub OAuth     │  /auth/github → /auth/callback
                └─────────┬──────────┘
                          │
                ┌─────────▼──────────┐
                │  FastAPI API        │  Port 8000
                │  (main.py)         │
                └─────────┬──────────┘
                          │
            ┌─────────────▼─────────────┐
            │  Repo Discovery Service   │  owner + collab + org + outside
            │  Collaborator Ingestion   │  GitHub → ugie_github_identities
            └─────────────┬─────────────┘
                          │
        ┌─────────────────▼─────────────────┐
        │  Webhook Edge (FastAPI)           │  HMAC-verified, Redis-deduped
        └─────────────────┬─────────────────┘
                          │
                   ┌──────▼──────┐
                   │    Redis    │  Event queue + dedup cache
                   └──────┬──────┘
                          │
                ┌─────────▼─────────┐
                │   RQ Workers      │  Backfill + Event Processor
                └─────────┬─────────┘
                          │
                   ┌──────▼──────┐
                   │  Supabase   │  PostgreSQL + REST API
                   └─────────────┘
                          ↑
                ┌─────────┴─────────┐
                │  Next.js Frontend  │  Port 3000
                │  (glassmorphism   │  Dashboard + Repo Detail
                │   dark UI)        │  Team + Kanban views
                └───────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker + Docker Compose
- [Supabase](https://supabase.com) project (free tier is fine)
- [GitHub OAuth App](https://github.com/settings/developers)
- (For local webhooks) [ngrok](https://ngrok.com) or similar tunnel

### 1. Clone & Configure

```bash
git clone <repo-url>
cd Webathon3

cp .env.example .env
# Edit .env with your real values (see Environment Variables section)
```

### 2. Generate Required Secrets

```bash
# Fernet encryption key for GitHub token vault
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# JWT signing secret
openssl rand -hex 32

# Webhook HMAC secret (also paste into GitHub repo webhook settings)
openssl rand -hex 32
```

### 3. Run Supabase Migration

Go to your Supabase project → **SQL Editor → New Query**, paste and run the full contents of:

```
backend/app/models/schema.sql
```

This creates all 7 tables: `ugie_users`, `ugie_repositories`, `ugie_commits`, `ugie_issues`, `ugie_pull_requests`, `ugie_github_identities`, `ugie_repo_collaborators`.

### 4. Start with Docker Compose

```bash
docker-compose up --build
```

This starts:
- `api` — FastAPI on port **8000**
- `worker` — RQ worker processing backfill + webhook events
- `redis` — Redis on port **6379** (Supabase is external)

### 5. Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on **http://localhost:3000**

### 6. Run Backend Locally (without Docker)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# API
uvicorn app.main:app --reload --port 8000

# Worker (separate terminal)
rq worker --url redis://localhost:6379/0 default
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_ANON_KEY` | ✅ | Supabase anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Supabase service-role key (backend only) |
| `REDIS_URL` | ✅ | Redis connection string |
| `GITHUB_CLIENT_ID` | ✅ | GitHub OAuth App client ID |
| `GITHUB_CLIENT_SECRET` | ✅ | GitHub OAuth App client secret |
| `GITHUB_WEBHOOK_SECRET` | ✅ | HMAC secret for webhook verification |
| `TOKEN_ENCRYPTION_KEY` | ✅ | Fernet key for token vault |
| `JWT_SECRET` | ✅ | Secret for signing session JWTs |
| `GITHUB_OAUTH_REDIRECT_URI` | ✅ | Must match GitHub OAuth App callback URL |
| `BACKFILL_DEPTH` | optional | Commits to backfill per repo (default: 200) |
| `ENVIRONMENT` | optional | `development` / `staging` / `production` |

---

## API Reference

### Authentication
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/auth/github` | Get GitHub OAuth authorization URL |
| `GET` | `/auth/callback` | Handle OAuth callback, returns JWT |
| `GET` | `/auth/status` | Token health + scopes |
| `GET` | `/auth/me` | Current user profile |
| `DELETE` | `/auth/disconnect` | Clear GitHub token |

### Repositories
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/repos` | List all discovered repos |
| `GET` | `/repos/{id}` | Single repo details |
| `POST` | `/repos/rescan` | Trigger full re-discovery |
| `POST` | `/repos/{id}/rescan` | On-demand backfill for one repo |
| `GET` | `/repos/{id}/commits` | Paginated commit list |
| `GET` | `/repos/{id}/issues` | Paginated issue list |
| `GET` | `/repos/{id}/pulls` | Paginated pull request list |

### Collaboration
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/repos/{id}/collaboration/collaborators` | Enriched collaborator list (avatar, permission, On-UGIE badge) |
| `POST` | `/repos/{id}/collaboration/collaborators/refresh` | Force re-fetch from GitHub |
| `GET` | `/repos/{id}/collaboration/board` | Kanban board (todo / in-progress / review / done) |

### Analytics
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/analytics/summary` | Cross-repo user metrics |
| `GET` | `/analytics/velocity/{repo_id}` | Velocity + entropy + burst windows |
| `GET` | `/analytics/contributors/{repo_id}` | Contributor rankings |

### Webhooks
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/webhooks/github` | GitHub webhook receiver |

### Observability
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (DB + Redis) |
| `GET` | `/metrics` | In-process counters + gauges |

**Interactive docs:** http://localhost:8000/docs

---

## Database Schema

| Table | Purpose | Idempotency Key |
|---|---|---|
| `ugie_users` | User identity + encrypted token vault | `github_id` |
| `ugie_repositories` | Repo graph + webhook state + backfill cursor | `(user_id, github_id)` |
| `ugie_commits` | Event-level commit truth | `(repo_id, sha)` |
| `ugie_issues` | Issues with assignee + state | `(repo_id, number)` |
| `ugie_pull_requests` | PRs with merge state + additions/deletions | `(repo_id, number)` |
| `ugie_github_identities` | Universal GitHub user registry → site user link | `github_login` |
| `ugie_repo_collaborators` | Per-repo collaborator membership + permissions | `(repo_id, github_identity_id)` |

---

## Webhook Setup (Local Dev)

```bash
# Start ngrok tunnel to expose local webhook endpoint
ngrok http 8000

# Use the ngrok HTTPS URL in GitHub webhook settings:
# https://<ngrok-id>.ngrok.io/webhooks/github
```

In GitHub: repo → **Settings → Webhooks → Add webhook**
- Payload URL: `https://<your-ngrok>.ngrok.io/webhooks/github`
- Content type: `application/json`
- Secret: value of `GITHUB_WEBHOOK_SECRET` in your `.env`
- Events: **Push, Pull Requests, Issues**

---

## Project Structure

```
Webathon3/
├── .env.example                   # Template for all environment variables
├── docker-compose.yml             # api + worker + redis services
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py                # FastAPI app factory
│       ├── config.py              # Env-based settings (pydantic-settings)
│       ├── database.py            # Supabase client dependency
│       ├── models/
│       │   └── schema.sql         # All 7 Supabase tables + indexes
│       ├── schemas/               # Pydantic I/O models
│       ├── routers/
│       │   ├── auth.py            # OAuth + JWT
│       │   ├── repos.py           # Repo CRUD + commits/issues/PRs
│       │   ├── collaboration.py   # Collaborator list + Kanban board
│       │   ├── analytics.py       # Intelligence endpoints
│       │   ├── webhooks.py        # HMAC-verified event ingestion
│       │   └── health.py          # Liveness + readiness + metrics
│       ├── services/
│       │   ├── github_client.py         # Paginated GitHub REST client
│       │   ├── github_oauth.py          # OAuth flow + Fernet token vault
│       │   ├── repo_discovery.py        # Full repo graph discovery
│       │   ├── commit_ingestion.py      # Idempotent commit upsert
│       │   ├── issue_ingestion.py       # Issues + PR ingestion
│       │   ├── collaborator_ingestion.py # GitHub collaborators → identity DB
│       │   └── analytics.py             # Frequency, entropy, burst detection
│       ├── workers/
│       │   ├── backfill_worker.py  # Resumable historical sync
│       │   ├── event_processor.py  # Webhook event type router
│       │   └── scheduler.py        # 5-minute periodic sync
│       └── utils/
│           ├── logging.py          # Structured JSON logging
│           ├── metrics.py          # Prometheus-style in-process counters
│           ├── signature.py        # HMAC webhook verification
│           └── retry.py            # Exponential backoff decorator
│
└── frontend/
    ├── package.json
    └── src/app/
        ├── page.tsx               # Dashboard: repo list + role filter
        └── repos/[id]/page.tsx    # Repo detail: commits, issues, PRs, team, board
```

---

## ⚠️ Security Notes

- **Never commit `.env`** — it is gitignored. Only commit `.env.example`.
- The `SUPABASE_SERVICE_ROLE_KEY` bypasses Row Level Security — keep it server-side only.
- GitHub tokens are Fernet-encrypted at rest in the database.
- JWTs expire after 7 days by default.
