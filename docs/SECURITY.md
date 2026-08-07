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
