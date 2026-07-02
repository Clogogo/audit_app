# FinanceAudit

A finance and payroll audit application: transaction tracking, bank statement reconciliation, AI-assisted receipt parsing, staff payroll (with loans and one-off salary advances), tax reporting, and audit logging.

- **Backend:** FastAPI (Python 3.13) + SQLAlchemy 2.0 — `apps/api/`
- **Frontend:** React 18 + Vite + TypeScript + Tailwind CSS — `apps/web/`
- **Monorepo:** Nx 21

## Production

| Component | Host | Notes |
|---|---|---|
| Frontend | [Vercel](https://vercel.com) | Deploys from `main` on every push |
| Backend  | [Render](https://render.com) | Web service `financeaudit-api`, deploys from `main` via a deploy hook |
| Database | [Neon](https://neon.tech) (managed Postgres) | `DATABASE_URL` set in Render's environment, not committed |
| Email    | [Maileroo](https://maileroo.com) | Transactional email — password reset, welcome, password-changed notices |

Both deploys are triggered by the `deploy-frontend` / `deploy-backend` jobs in [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml), gated to run only `on: push` to `main`. Render's own auto-deploy is disabled (`autoDeploy: "no"` on the service) — the GitHub Actions deploy hook is the only thing that triggers a backend deploy.

The backend deploy job polls the Render API until the new deploy reports `live` (or fails fast on `build_failed`/`deactivated`/`canceled`), so a red `Deploy → Render` check means the deploy did not succeed, not just that the API call timed out.

## Branching & release flow

```
feature/* ──PR──▶ staging ──PR──▶ main ──auto-deploy──▶ production
```

- **`staging`** — integration branch. PRs require all 4 CI checks to pass (`Backend — checks`, `Backend — tests (Postgres)`, `Frontend — build`, `Frontend — tests`). No required approvals, but branch protection is enforced for admins too.
- **`main`** — production. Same 4 checks, plus:
  - `strict` — the PR branch must be up to date with `main` before merging
  - `required_conversation_resolution` — all GitHub Copilot automated review threads must be resolved before merging
  - Use `--merge` (regular merge commit) for `staging → main` PRs — **not squash**

GitHub Copilot's automated PR reviewer (`copilot-pull-request-reviewer`) leaves inline comments on most PRs. Treat its findings as you would a human reviewer's — fix real issues, add regression tests, then resolve the thread once addressed (resolving without fixing won't satisfy the `main` branch protection rule's *intent*, but GitHub only enforces that threads are marked resolved, not that they were acted on — don't abuse that).

Standard PR cleanup after merging: delete the feature branch (`gh pr merge --delete-branch`), then `git checkout staging && git pull`.

After every `staging → main` merge, the [Sync main → staging](.github/workflows/sync-main-to-staging.yml) workflow automatically opens a PR merging main back into staging (with auto-merge enabled), so staging never shows as "behind main". To check whether staging and main actually differ in content: `git diff origin/main origin/staging --stat`.

## Local development

### Prerequisites
- Node.js 22, npm
- Python 3.13 (a venv at `apps/api/.venv` is expected — Homebrew Python on macOS is externally managed and won't allow global `pip install`)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (`brew install tesseract` on macOS) — required for receipt OCR

### Setup

```bash
# Install JS dependencies (root + frontend)
npm install

# Python dependencies
cd apps/api
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # then fill in the values below
cd ../..
```

### Environment variables

Backend (`apps/api/.env`, see [`.env.example`](apps/api/.env.example)):

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | Yes | App refuses to start without it — no insecure default |
| `ALGORITHM` | No | Defaults to `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Defaults to `1440` (24h) |
| `OPENROUTER_API_KEY` | For AI features | Routes through [OpenRouter](https://openrouter.ai) — `.env.example` lists this as `OPENAI_API_KEY`, which is stale; the code reads `OPENROUTER_API_KEY` |
| `DATABASE_URL` | No locally | SQLite (`finance.db` at repo root) if unset; Postgres in production |
| `FRONTEND_URL` | Production only | Used for CORS and to build links in password-reset/welcome emails |
| `MAILEROO_API_KEY` / `MAILEROO_FROM_EMAIL` | For password reset emails | Must both be set together — `/auth/forgot-password` short-circuits without creating a token if either is missing |
| `UPLOAD_DIR` | No | Defaults to `uploads/` locally; `/tmp/uploads` in production (Render free tier has no persistent disk) |
| `MAX_UPLOAD_SIZE_MB` | No | Defaults to `50` |
| `SQL_ECHO` | No | Set `True` to log SQL queries |

> Note: `render.yaml` and `.env.example` also reference `CORS_ORIGINS`, but the current code only reads `FRONTEND_URL` for CORS — `CORS_ORIGINS` is unused.

Frontend (`apps/web/.env` or root `.env` consumed by Vite): `VITE_API_URL` — the backend base URL. Falls back to `http://localhost:8000` if unset.

### Run

```bash
npm start                       # both frontend (:4200) and backend (:8000) in parallel
npx nx run web:serve            # frontend only
npx nx run api:serve            # backend only — uvicorn --reload
```

- Frontend: http://localhost:4200
- Backend + interactive API docs: http://localhost:8000/docs

### Tests

```bash
# Backend
cd apps/api && source .venv/bin/activate && pytest tests -q

# Frontend
npx nx run web:test             # vitest
npx tsc --noEmit -p apps/web/tsconfig.app.json   # typecheck
npx nx run web:build            # production build
```

CI runs the backend suite against a real Postgres service container (not SQLite) — SQLite has previously hidden production-only bugs around boolean-column comparisons and date functions.

## Key features

- Transaction CRUD with full audit logging
- Bank statement import (CSV/Excel/PDF) with a reconciliation engine
- AI receipt upload: Tesseract OCR + `pdfplumber` → LLM (via OpenRouter) to pre-fill the transaction form
- Staff Loans — installment-based, recovery driven by recorded `StaffLoanPayment` entries (not a formula)
- Advance Payment (IOU) — one-off salary advances, fully recovered from the next payroll run processed after they're issued
- Payroll — computes net pay per staff member per period, factoring in loan and advance deductions (capped together so they can never exceed a line's earnings) and other deductions
- Tax / financial statements, asset register, audit log, CSV/PDF report export
- Dark mode (class-based Tailwind theming, persisted, no flash-of-wrong-theme on load)

## Project structure

```
apps/
  api/                  FastAPI backend
    routers/            One file per resource (transactions, payroll, advance_payments, ...)
    models.py           SQLAlchemy models
    schemas.py           Pydantic schemas
    tests/               pytest suite
  web/
    src/
      pages/             Route-level components
      components/        Shared UI components
      api/                Typed API client (client.ts, types.ts)
      contexts/           React context providers (auth, etc.)
.github/workflows/      CI + deploy pipeline
render.yaml             Render service definition (backend)
vercel.json             Vercel build config (frontend)
```

## Security notes

- Every router except the public auth endpoints (`/auth/login`, `/auth/register`, `/auth/forgot-password`, `/auth/reset-password`) requires a logged-in user via JWT.
- Passwords are hashed with bcrypt; password reset uses single-use, expiring, emailed tokens (not a recovery code).
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, HSTS, `Referrer-Policy`) are applied to every response.
- Registration is currently open (no invite code) — anyone can self-register an account.
