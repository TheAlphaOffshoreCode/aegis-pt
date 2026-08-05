# Security

The full audit is L13. This file records the posture as it is built, loop by loop, so the
final audit verifies claims instead of discovering them.

## Secrets

| Secret | Where it lives |
|---|---|
| `AEGIS_SECRET_KEY` | environment / `.env`, never versioned |
| `AEGIS_DATABASE_URL` | environment / `.env` |
| Anthropic API key (L9) | environment, read in the backend only — never reaches the browser |

`.env` is in `.gitignore`. `alembic.ini` ships with an empty `sqlalchemy.url` precisely so
no connection string is ever committed; the URL is resolved in `migrations/env.py` from
settings.

`Settings.secret_key` has no default and requires at least 32 characters. The application
refuses to start otherwise — a development fallback secret is exactly how a weak key reaches
production.

## Transport and headers

CORS is restricted to the origins listed in `AEGIS_CORS_ORIGINS` (defaults to localhost),
with an explicit method and header allowlist. `*` is never acceptable, including in
development, because the credentialed PWA is the only client.

Security headers, rate limiting and error handling that never leaks a stack trace are
scheduled for L13.

## Authorization

L0 exposes only `/health`, `/` and `/static/*` — no user data on any of them.
From L2 every endpoint carries an explicit authorization dependency; a route without one is
a defect, not a default.

Segregation of duties (the issuer never signs their own permit) is enforced in the rule
engine, not in the interface.

## Data integrity

- Foreign keys are enforced on SQLite (`PRAGMA foreign_keys=ON` on every connection).
- All SQL goes through SQLAlchemy with bound parameters. Raw string interpolation into SQL
  is banned.
- `audit_events` is append-only, hash-chained, and verified by a dedicated checker (L6).

## AI surface

The model is confined to `app/ai/`. Its tools are read-only by construction and receive
data already filtered by the authenticated user's scope. Permit content is untrusted input:
prompt-injection review of every template is part of L13.

## Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| — | — | No audit performed yet (L13) | — |
