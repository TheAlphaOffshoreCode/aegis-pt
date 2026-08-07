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

## Authentication (L2)

Passwords are stored as **Argon2id** hashes (`argon2-cffi`, library defaults). The plaintext
is never stored, logged or returned; `senha_hash` is `NOT NULL` with an empty default, and an
empty hash authenticates nobody.

Sessions are **JWT `HS256`** signed with `AEGIS_SECRET_KEY`. `jwt.decode` always receives an
explicit `algorithms=["HS256"]`: without it, a token forged with `alg: none` would be
accepted. There is a test that forges exactly that one, plus a wrong-key token and an expired
token.

The token carries only `sub`, `iat` and `exp`. **No profile inside the token** — the profile
travels with the user in the database and is read on every request, so a revoked profile or a
deactivated account stops working immediately instead of surviving until expiry.

Login answers the same `401` for wrong password, unknown matrícula and deactivated account,
and burns an equivalent Argon2 verification when the matrícula does not exist, so neither the
message nor the timing reveals who exists on board.

Not covered yet: **login rate limiting and account lockout** (L13, with the other hardening),
and there is **no token revocation list** — a leaked token is valid until it expires.

## Authorization

L0 exposes only `/health`, `/` and `/static/*` — no user data on any of them.
From L2 every endpoint carries an explicit authorization dependency; a route without one is
a defect, not a default.

`exigir_perfis(...)` in `app/security/dependencias.py` is the RBAC gate; `admin` passes
everything by design. `unidades_visiveis()` resolves the user's scope and **fails closed** —
a user with no posting and no global profile sees an empty set, not everything. Per rule 5
this set enters the query, never filters the result: filtering afterwards is still a leak,
just one with an extra step.

The development seed refuses to run outside `environment=development`, and the guard sits in
`semear()` itself rather than only in `main()` — it creates accounts with a known password.

Segregation of duties (the issuer never signs their own permit) is enforced in the rule
engine, not in the interface.

## The rule engine (L4)

Rule 2 lives here in full: **no safety-relevant number comes out of a language model.** Every
deadline, count and expiry is computed in `app/rules/`, from tables in `exigencias.py` — required
certification per work type, required attachments, maximum window length, incompatible
simultaneous work. That file is deliberately data rather than logic, so changing a requirement
does not mean editing control flow.

The rules are **pure functions**: they receive the permit and the already-loaded concurrent
permits and return pendencies. Nothing queries the database inside a rule, which is what lets
each limit be tested on its own instead of through half the system.

Two decisions worth stating because they are conservative on purpose:

- **Certification is checked against the end of the permit's window, not against today.** A
  certificate expiring mid-service leaves the worker unqualified exactly while exposed.
- **Rule 8 (segregation of duties) is enforced in the engine.** The issuer cannot sign their own
  permit in any approving role, and no one signs in a role their profile does not hold —
  including `admin`, which administers the system and does not answer technically for the
  document.

`GET /pts/{id}/pendencias` exposes the verdict without changing anything. Enforcing it at the
transition is L5: the engine decides, the state machine applies.

## The approval flow (L5)

The state machine in `app/workflow/maquina.py` is an explicit graph, and rule 6 falls out of
that rather than being enforced by a check: **a skipped step is not a case to reject, it is a
transition that does not exist.** `ARQUIVADA` has no outgoing steps, `SUSPENSA` is reachable
only from `EM_EXECUCAO`, and `REJEITADA` leads only back to `RASCUNHO`.

Entering `EM_EXECUCAO` — from release or from a resumed suspension — is the only point that
demands the rule engine be clean. It is where the permit stops being paper and becomes people
exposed.

**Every transition writes to `audit_event` before the commit**, with actor, timestamp, device,
IP, geolocation and document hash, chained as `hash_evento = H(hash_anterior + payload)`. The
chain is written here, in L5, rather than in L6, because rule 6 requires the record to exist at
the moment the transition happens — writing transitions now and chaining later would mean
auditing a past that was never captured. Only INSERTs exist in `app/audit/trilha.py`; nothing
in the system updates or deletes an event (rule 4). The verifier and the compensating event
are L6.

Device and IP are read from the request, never accepted from the body. Geolocation does come
from the client, because only the client has it — it is recorded as received, and never
invented when missing.

## The audit trail (L6)

Three separate guarantees, because they fail in different ways:

**Append-only is enforced, not documented.** A `before_flush` listener on `SessionLocal`
raises `TrilhaImutavel` on any attempt to update or delete an `AuditEvent`. It is registered on
the sessionmaker rather than on the `Session` class — the same trap paid for in L0 with
`PRAGMA foreign_keys`, where a class-level listener would reach every session in the process.

**The chain detects tampering.** `verificar_cadeia` recomputes each link from what is stored
and compares. Two checks per link, because they catch different things: the stored
`hash_anterior` must match the previous link (catches a **removed** or reordered event), and
the recomputed `hash_evento` must match the record (catches an **altered** one). Verified
against the development database by editing a row through raw SQL — the realistic attack,
since it bypasses the application entirely — and confirming the chain closes again once the
value is restored.

**The payload format is versioned, and frozen.** `app/audit/formato.py` holds `VERSAO_PAYLOAD`,
and every event stores the format it was sealed with. This is not ceremony: adding
`evento_compensado_id` to the payload in this very loop invalidated every event written in L5
until each was verified by its own format. A verifier that cries wolf is worse than none, so
changing the payload without bumping the version is a defect, and the older format must stay
buildable.

Corrections never rewrite. `POST /pts/{id}/trilha/{evento_id}/compensacao` appends an event
referencing the original, restricted to `coordenador` and `oim`. The wrong record stays
visible.

## Uploads (L7)

An uploaded file is hostile input that later gets served back. Four separate defences:

- **The path is never the client's.** Files land at `{upload_dir}/{pt.uuid}/{uuid4}{ext}`, and
  any directory component in the submitted name is stripped before it is even stored as a
  label. `caminho_absoluto()` still re-checks that the resolved path sits under the upload
  directory — cheap, and the difference between a bug and a leak the day that column can be
  influenced.
- **Extensions are an allowlist**, not a denylist. `.html` and `.svg` are excluded on purpose:
  both render as pages.
- **Serving is always `attachment` plus `nosniff`**, with the media type taken from the
  server's own map rather than the `Content-Type` the client declared. The
  `Content-Disposition` header is produced by Starlette, not concatenated by hand — the
  filename came from the client, and hand-built headers are how quotes and newlines get in.
- **`upload_dir` must never point inside `static/`**, which is served directly and would turn
  every upload into public content.

The SHA-256 is computed over the received bytes and is what proves the file did not change
after being attached. Size is capped during the read, and a partial file is deleted rather
than left orphaned.

Attachments do not enter the permit's document hash: the hash covers the form that people
sign. Attaching and removing are recorded in the trail with actor, timestamp, context and the
file's own hash — and removal is only possible while the permit is still a draft.

## Search and dossier (L8)

**The count is scoped too.** `total` in a search result goes through the same scope and filters
as the listing. A global count would answer "how many permits exist beyond your reach?" without
returning a single one of them — a leak that returns no rows is still a leak.

A filter is not an escape hatch: passing `unidade_id` for a unit outside the caller's scope
returns empty rather than that unit. Scope is applied always, filters only narrow further.

`limite` is capped at 200, so no single call dumps the archive. Text search goes through bound
parameters like every other query.

The dossier exposes nothing new — it composes what the caller could already read one endpoint
at a time, and answers `404` outside scope like the permit itself.

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
