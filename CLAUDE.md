# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build contract — read this before anything else

This project is built in **numbered loops, L0 through L13**, one at a time. Each loop has a
closed scope and an objective acceptance criterion.

- **Finish a loop, then STOP.** Emit the loop report and wait for explicit authorization
  ("OK, siga para L{n+1}"). Never chain two loops.
- If a loop's acceptance criterion fails, **do not advance** — fix it inside the same loop and
  re-emit the report.
- `LOOP_STATE.md` is the single source of truth for resuming. Read it first; update it last.
  It carries the open pendencies and the exact resume point.
- Inside every loop run seven steps: plan → build → test → self-review → security → doc →
  report. If test, self-review or security fails, go back to build **within the same loop**.
- Never leave `# TODO: implement later` on a critical path. Anything that does not fit the
  current loop becomes a declared pendency in `LOOP_STATE.md`.

The loop report format is fixed — copy the shape already used in `LOOP_STATE.md`: delivered,
acceptance, tests, security check, decisions, pendencies, how to run, next loop.

## Inviolable rules (violating one fails the loop)

1. The AI never approves, releases or closes a permit. No technical path may exist — every
   tool exposed to the model in `app/ai/` is read-only or draft-creating.
2. No safety number comes out of a language model. Distances, loads, deadlines, counts and
   expiry dates come from deterministic, tested code in `app/rules/`.
3. Every AI answer cites the source permits. Nothing retrieved means "não encontrei" — never a
   plausible answer without a source.
4. `audit_events` is append-only. No `UPDATE`, no `DELETE`. A correction is a new compensating
   event referencing the original.
5. AI tools inherit the authenticated user's scope, applied **before** the model sees data.
6. No state transition may be skipped, and none happens without actor, timestamp, context and
   document hash.
7. API keys never reach the frontend or the repository — environment variables read in the
   backend only.
8. Segregation of duties: the issuer never approves their own permit. Enforce it in the rule
   engine, not only in the UI.

## Commands

Windows / PowerShell. One command per line — never multi-line with backslashes, never assume
`make` or Unix tooling.

Only Python 3.14 is installed on this machine, so the project uses its own venv. After
activating, the interpreter is `python`, **not** `py`:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
python -m pytest -q
python -m pytest tests/test_bootstrap.py::test_health_responde_200 -q
python -m alembic upgrade head
python -m alembic downgrade -1
python -m alembic revision --autogenerate -m "descricao"
```

Without activating, prefix with `.\.venv\Scripts\python.exe` instead of `python`.

There is no linter or formatter configured yet.

## Architecture

Layering is strict, and the split is the point of the design:

| Layer | Rule |
|---|---|
| `app/routers/` | HTTP only — parse, authorize, delegate. **Never** business logic here. |
| `app/services/` | orchestration across repositories, rules and audit |
| `app/rules/` | the deterministic rule engine: every business rule lives here, isolated and independently testable, returning structured pendencies (code, severity, responsible) |
| `app/workflow/` | the permit state machine and its transitions |
| `app/audit/` | append-only trail, `hash_evento = H(hash_anterior + payload)`, chain verifier |
| `app/ai/` | the only place the model is reached; read-only tools, scope applied before the call |
| `app/security/` | auth, RBAC, hashing |

A rule that leaks into a router is a defect, even when the tests pass.

### Permit lifecycle

```
RASCUNHO → VALIDACAO → ANALISE_SMS → APROVACAO → LIBERACAO → EM_EXECUCAO → ENCERRADA → ARQUIVADA
```

Deviations: `SUSPENSA` (only from `EM_EXECUCAO`) and `REJEITADA` (returns to `RASCUNHO`).

### Traps already paid for — do not undo these

- **`app/models/__init__.py` is the metadata registry.** A model not imported there is invisible
  to `Base.metadata`, so `alembic revision --autogenerate` silently ignores it.
- **`alembic.ini` ships with `sqlalchemy.url` empty on purpose.** The URL is resolved in
  `migrations/env.py` from `Settings`, so no connection string is ever committed.
- **`render_as_batch` is on for SQLite** in `migrations/env.py`. SQLite cannot do a full
  `ALTER TABLE`; without batch mode, column downgrades break.
- **`PRAGMA foreign_keys=ON` is set on every SQLite connection** in `app/database.py`, bound to
  the engine instance rather than the `Engine` class. Without it the dev database enforces no
  foreign key at all and the model lies about its own integrity.
- **Static files mount at `/static`, not `/`.** A mount at the root would swallow every router
  included after it, since Starlette matches routes in registration order.
- **`Settings.secret_key` has no default and requires 32 characters.** The app refuses to start
  without a real secret — a development fallback is how a weak key reaches production.
- **`tests/conftest.py` sets `AEGIS_*` environment variables before importing `app`,** because
  `app/database.py` builds the engine at import time. Env vars outrank the `.env` file.

## Conventions

- **Domain names in Portuguese** (`permissao_trabalho`, `assinatura`, `pendencia`), **technical
  structures in English** (`router`, `service`, `repository`, `engine`).
- Short docstring on every public function. No comments restating the code — comment the *why*,
  especially where a non-obvious constraint is being satisfied.
- Product UI and domain vocabulary are Brazilian Portuguese; `README.md`, `CLAUDE.md` and
  `docs/` are English.
- Business conflicts (blocking pendency, invalid transition) return `409` with the structured
  pendency list, never a bare message.
- Frontend is vanilla PWA — no framework, no build step, no CDN in production. Visual identity
  is mandatory on every screen: `#0B0F14` background, `#38BDF8` cyan, `#F59E0B` amber, Oswald
  for headings, JetBrains Mono for data and identifiers, GCS/HUD density.

## Tests that must exist by the end

Transition skipping rejected · approval with blocking pendency rejected · issuer cannot sign
their own permit · audit chain detects tampering · AI tools cannot write · user scope applied
before the model sees data · expired certification blocks release · offline sync never silently
overwrites a remote change.
