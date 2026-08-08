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
- **The `doc` step includes `README.md`**, not only `LOOP_STATE.md` and `docs/`. The README is
  the only artifact no test can fail for, so it rots silently — it went stale twice in a single
  day. Status badge, current state, endpoint table, test count and roadmap all move with the
  loop. Verify every number before writing it; do not estimate.
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
python -m app.seed
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
- **Enum columns go through `enum_col()`** in `app/models/tipos.py`. A bare `Enum(...)` stores
  the member *name* (`NR_35`), not its value (`NR-35`), and the database silently stops
  matching the norm, the API and the screen.
- **`Base.metadata` carries a `NAMING_CONVENTION`.** Batch mode recreates the table on SQLite,
  and an anonymous constraint does not survive that. Never add a constraint without a name.
- **`audit_event.pt_id` is `ON DELETE RESTRICT` on purpose.** Deleting a permit with a trail
  would delete the evidence with it. There is a test; do not "fix" it into CASCADE.
- **The permit's `estado`, `numero`, `uuid` and `versao` have no write schema.** They are the
  server's to decide — a client that can post its own state can post `LIBERACAO`.
- **`jwt.decode` always gets an explicit `algorithms=[...]`.** Without it a token forged with
  `alg: none` is accepted. There is a test that forges exactly that.
- **The token carries no profile.** Profile and posting are read from the database on every
  request, so revoking access takes effect now instead of when the token expires.
- **`HTTPBearer(auto_error=False)`.** The default answers `403` for a missing credential, and
  a missing credential is `401`.
- **Adding a `NOT NULL` column needs `server_default` in the migration** whenever the table
  already has rows. Autogenerate omits it and the upgrade fails on a populated database.
- **`/pts/modelos/{tipo}` is registered before `/pts/{pt_id}`.** Starlette matches in
  registration order; reversed, the literal route is never reached.
- **Out of scope answers `404`, never `403`.** "You may not see this one" already confirms
  the permit exists.
- **`_obter_ou_criar` in the seed does not update rows that already exist.** Anything a later
  loop adds to `usuario` needs an explicit repair pass, or a database seeded by an earlier
  loop silently keeps the old shape. Cost so far: senha and lotação, both with tests.
- **Foreign keys coming from the payload get validated in the service**, not left to the
  database. An `IntegrityError` at commit is a `500` where a pendency naming the field was
  possible.
- **Every datetime column uses `UTCDateTime`, never bare `DateTime(timezone=True)`.** SQLite
  stores no offset, so a plain column returns naive there and aware from PostgreSQL. Comparing
  the value read against `agora_utc()` then raises `TypeError` in one environment and passes in
  the other. Normalizing at the database edge fixes it for every consumer at once.
- **Rules in `app/rules/` take data and return pendencies — they never query.** The service
  loads what a rule needs (concurrent permits, for instance) and passes it in. That is what
  keeps each limit testable without building half the system around it.
- **The document hash excludes `estado`.** A signature signs content, not position in the flow.
  If the hash moved with the state, two signatures of the same version would not match and
  nothing could be verified later.
- **Signatures are unique per `(permit, step, version)`, not per role.** The same role signs
  different steps on purpose — the executant starts and closes the work. Steps that repeat
  within a version (suspend, resume) carry `assina=False` and live only in the trail.
- **`app/audit/trilha.py` only ever INSERTs.** No code path updates or deletes an
  `audit_event`; a correction is a new compensating event (rule 4).
- **In tests, `db` and the request use different sessions.** After a `TestClient` call changed
  something, call `db.expire_all()` — otherwise the test reads its own stale identity map and
  fails for the wrong reason.
- **The audit payload format is a frozen contract.** Changing what goes into the hash without
  bumping `VERSAO_PAYLOAD` in `app/audit/formato.py` retroactively invalidates every event
  already sealed, and the verifier starts reporting tampering that never happened. Add a
  field → bump the version → keep the previous format buildable.
- **`montar_payload` is used by both the writer and the verifier.** If the verifier rebuilt
  the payload on its own, any drift between the two would look like tampering.
- **Anything written into an `audit_event` must be set at creation.** Assigning an attribute
  afterwards marks the object dirty and the append-only guard refuses the flush — correctly.
- **Never build a `Content-Disposition` by hand.** Pass `filename=` to `FileResponse` and let
  Starlette encode it; the name came from the client, and manual headers are how quotes and
  newlines get injected.
- **`AEGIS_UPLOAD_DIR` must stay outside `static/`.** That directory is served as-is, so an
  upload landing there becomes public content.
- **f-strings cannot reuse the outer quote character** — that is 3.12+, and CI runs 3.11.
- **A paginated `total` must carry the same scope and filters as the page.** A global count
  reveals how many records exist beyond the caller's reach without returning any of them.
- **Sanitize client-supplied filenames with `PureWindowsPath`, never `Path`.** On Linux `Path`
  does not treat `\` as a separator, so `..\..\sam.pdf` survives intact on the server while
  looking sanitized on a Windows dev machine. `PureWindowsPath` handles both separators on
  every platform. This one shipped and was caught by CI, not locally.
- **`tests/conftest.py` sets `AEGIS_ANTHROPIC_API_KEY` to empty on purpose.** A key present in
  the developer's `.env` would make the suite call the real API and bill for it. Empty means
  the agent only runs with the fake client the test injects — the suite has no network path.
- **`temperature`, `top_p` and `top_k` are rejected with `400` on Opus 5**, and
  `thinking.budget_tokens` with them. Reasoning is adaptive and on by default, and it shares
  `max_tokens` with the answer — a tight ceiling truncates mid-thought. Reach for
  `output_config: {"effort": ...}` instead of sampling knobs. There is a test asserting the
  request carries none of the three.
- **AI sources are collected from what the database returned, never from the answer's text.**
  `ferramentas.executar()` returns the permits it actually read; `agente._com_fontes` throws
  the text away when that list is empty. Reading permit numbers out of the reply with a regex
  would make rule 3 depend on the model, which is the whole thing being avoided.
- **Check `stop_reason == "refusal"` before touching `content`.** On a refusal the content
  comes back empty or partial, and code that assumes a text block raises there instead of
  answering.
- **A PT cannot be born incomplete.** `validar_respostas` runs in `criar_pt` and
  `atualizar_pt`, not in `avaliar_pt` — form completeness is an invariant of the write
  boundary, and the rule engine never re-checks it. So relaxing creation would let an
  incomplete permit walk the whole flow with nothing to stop it. That is why `/ai/rascunho`
  takes `respostas` in the request instead of leaving them for later.
- **The audit event-type catalogue is open; the payload format is not.** A new kind of event
  (`pt.criada_por_ia`) is a new *value* for `tipo_evento`, which the payload already carries —
  no `VERSAO_PAYLOAD` bump, no retroactive invalidation. Reach for a new event type before
  reaching for a new payload field.
- **`output_config` carries both `effort` and `format`.** Structured output and tool use work
  in the same request: the model calls tools mid-conversation and the *final* answer is bound
  to the schema. Every object in that schema needs `additionalProperties: false`, and
  recursive schemas and numeric bounds are not supported.
- **Validate the model's structured output again on arrival.** The schema constrains shape,
  not meaning — a `tipo_trabalho` outside `TipoTrabalho` still comes back as a valid string.
  Pydantic re-validation is what turns that into a refusal instead of a broken permit.

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
