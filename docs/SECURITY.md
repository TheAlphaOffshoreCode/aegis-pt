# Security

Written loop by loop as the posture was built, so the closing audit could verify claims rather
than discover them. **L13 is complete**: the Findings table at the end resolves every pendency
declared across L0–L12 into a fix with a test behind it, or an accepted risk with its reason.

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

Security headers, rate limiting and non-leaking error handling arrived in L13 — see
Hardening below for what each one is and why the CSP could be this strict.

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

Login is rate-limited since L13 (five attempts per minute, per origin and matrícula). There is
still **no token revocation list**: a leaked token is valid until it expires, at most one shift.
What it carries is only the identity — profile and posting are re-read on every request, so
revoking a profile or deactivating an account takes effect immediately. See Findings.

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

## Indicators and alerts (L11)

**Every number is a `COUNT`.** A dashboard looks harmless until someone plans a shift from it.
Nothing in `/indicadores` is estimated, sampled or inferred, and none of it passes through a
language model — the same rule 2 that governs the engine, applied where it is easiest to
forget.

**Scope enters the query, for alerts too.** That is why an alert stores its own `unidade_id`
instead of deriving it from the entity: the filter has to work without knowing whether it is
looking at a permit or a certification. A user posted to one unit does not see the other
unit's alerts, and `sincronizar` — which runs over the whole operation — is restricted to
`coordenador` and `oim`. Whoever triggers it is deliberately not whoever reads it: an alert
that only exists when the right person clicks is not an alert.

**Alerts are resolved, never deleted.** When a condition disappears the row stays, marked
`resolvido`. Deleting it would erase the fact that the problem existed, which is precisely
what an investigation later needs. Escalation is a function of the clock, not of how often
the sync ran, so the process cannot inflate its own urgency by running more often.

**`responsavel` is derived, not stored.** Storing it would create a second truth; a change to
the escalation ladder would leave old rows pointing at people who no longer answer for them.

Two limits worth stating plainly: there is **no scheduler** in this application, so alerts are
only as fresh as the last call to `/alertas/sincronizar` — nothing fires on its own, and a
deployment that forgets the cron gets a silent board rather than a wrong one. And an alert
that reaches the top of the ladder stays there: above the OIM there is nobody on board to
escalate to, which is a fact about the vessel, not a gap in the code.

## Offline operation (L12)

The threat here is not an attacker; it is a tablet that has been out of signal for half an
hour and then reconnects. What it must never do is quietly win.

**Every draft edit declares what it saw.** `PATCH /pts/{id}` requires `visto_em`, the
`atualizado_em` the client read before editing. If the permit moved on in between, the write
is refused with `409 edicao_desatualizada` and nothing is lost — the correction that arrived
first stays, and the person who arrived second is told when it changed and asked to reload.
Required rather than optional, because a client that does not say what it saw cannot claim it
overwrote nothing.

**Signing a step requires connectivity, deliberately.** Transitions are not queued. The rule
engine's verdict holds at the instant of the transition, so queueing a release would let
someone walk away from the screen believing they authorised work that the server has not yet
agreed to. Reading works offline; authorising does not, and the screen says so.

**The queue never resolves a conflict on its own.** A queued edit that comes back `409` is
marked and shown on the permit's own screen with the option to discard it. Retrying it
automatically would be picking a winner in the dark.

**The service worker caches reads only.** No `POST`, no `PATCH`, and `/auth` is excluded from
the cache entirely — a token in the cache is a credential left on the disk of a shared deck
tablet. Data served from the cache carries `X-Aegis-Do-Cache`, and the screen labels it, so
nobody decides from a figure that may be hours old believing it is current. Only `200`
responses are cached: caching a `401` would keep showing "no access" after the login came
back.

**Writes never pass through the service worker.** A `POST` replayed silently by a worker is
the classic origin of the duplicate nobody can explain afterwards; the queue lives in the
application, where what is pending can be shown.

Two limits worth stating: the queue is in `localStorage`, which is synchronous and around
5 MB — enough for draft corrections, not for offline attachments; and the token also lives in
`localStorage`, which is readable by any script on the origin. The second is only acceptable
because the application ships no third-party script and no CDN — the moment either appears,
this needs revisiting along with the L13 hardening.

## Data integrity

- Foreign keys are enforced on SQLite (`PRAGMA foreign_keys=ON` on every connection).
- All SQL goes through SQLAlchemy with bound parameters. Raw string interpolation into SQL
  is banned.
- `audit_events` is append-only, hash-chained, and verified by a dedicated checker (L6).

## The AI surface (L9)

The model is confined to `app/ai/`, and the three AI rules are enforced by structure rather
than by instructions — a prompt is a request, and this is a safety system.

**Rule 1 — the model cannot act.** There are three tools and all of them read:
`buscar_pts`, `detalhar_pt`, `pendencias_da_pt`. `app/ai/ferramentas.py` contains no `add`,
no `commit`, no `delete` and no transition, so there is no technical path by which any prompt
approves, releases or closes a permit. A test asserts the tool set itself, so adding a fourth
tool fails the suite until someone proves it only reads.

**Rule 2 — no safety number is generated.** Deadlines, validity windows, counts and verdicts
reach the model already computed by `app/rules/`. The tool descriptions say to reproduce them
as received, but the guarantee is that the model has no other source: it never sees a raw
date arithmetic problem to solve.

**Rule 3 — no answer without a source, enforced in code.** `executar()` returns the permit
numbers the query actually returned, and the agent accumulates them. If that list is empty,
`_com_fontes` discards the model's text and substitutes "não encontrei". A model that
hallucinates a permit number in the text does not put it in `fontes`, because `fontes` never
comes from the text. Both cases are tested.

**Rule 5 — scope applied before the model sees data.** Every tool runs against the server's
authenticated `Usuario` through `aplicar_escopo`, in the query. The model does not choose whom
it is answering for and cannot ask about a unit it was not given. A permit outside scope
answers exactly like one that does not exist — distinguishing them would already confirm it
exists somewhere. Tested by running the same scripted conversation as two different users.

**Rule 7 — the key.** `AEGIS_ANTHROPIC_API_KEY` is read only in `construir_cliente()`, in the
backend. Nothing under `static/` mentions it, no route returns it, and the browser talks to
`POST /ai/consulta` — never to api.anthropic.com. Without the key the AI routes answer `503`
and the rest of the application starts normally, so a missing key degrades one feature instead
of the system.

The suite never reaches the network: `tests/conftest.py` sets the key to empty on purpose (a
key in the developer's `.env` would otherwise make the tests call out and bill), and the agent
takes an injected client.

## Draft generation (L10)

The same confinement, extended to a path that writes — and the write is the interesting part.

**The model still cannot act.** `POST /ai/rascunho` creates a permit in `RASCUNHO` through
`permissoes.criar_pt`, the same call the `POST /pts` route makes: same validation, same
numbering, same trail, same signature chain ahead of it. There is no AI-only shortcut and no
step is skipped. The tools the model reaches remain the three read-only ones from L9 — the
creation happens in the service after the model has finished and its output has been
validated, not through anything the model can call.

**The model writes no safety number, and never sees one.** The proposal schema has exactly
five fields — work type, description, hazards, controls, justification — with
`additionalProperties: false`, so there is no shape in which a form answer could come back.
Measurements, the validity window, the unit and the area travel in the request from the
person, are passed through untouched, and are never included in what the model reads. A test
asserts both halves: the stored answers equal what the caller sent, and none of their values
appear anywhere in the request sent to the API.

**Provenance survives.** The trail records `pt.criada_por_ia` instead of `pt.criada`. This
rides the open event-type catalogue rather than the payload, so nothing about the frozen hash
format changed and no version bump was needed — an AI-drafted permit stays identifiable for
the life of the document, including in an incident investigation years later.

**The proposal is validated before it is trusted.** The structured-output schema constrains
the shape; Pydantic then re-validates it, which is what catches a work type outside the
domain. Anything unusable raises before a permit exists — `502`, nothing written.

A note on where the line landed: a draft cannot be born incomplete, because required-field
validation lives at the write boundary rather than in the rule engine. That is why the
measurements arrive with the request instead of being filled in later. It is a real
constraint on the flow, declared below rather than worked around — and working around it for
the AI path specifically would have given the model a route through validation that a person
does not have.

Two exposures remain open and are declared rather than assumed away:

- **Prompt injection through permit content.** A requisitante writes the description, and that
  text reaches the model inside a tool result. It cannot make the model act — there is nothing
  to act with — but it can push the *wording* of an answer. Mitigation is L13, together with
  the review of every template.
- **No rate limit on `/ai/consulta`.** Each query costs tokens, and any authenticated user can
  repeat it. Bounded per query (6 tool iterations, 8000 output tokens), unbounded per user.
  L13, with the other hardening.

## Hardening (L13)

The closing loop's job was not to add features but to settle the debt: every pendency declared
across L0–L12 is now either fixed with a test behind it, or an accepted risk written down with
its reason. What follows is the audit.

**Security headers on every response**, including error responses — a header that disappears
exactly where something went wrong is not a control. The CSP is unusually strict because the
product allows it to be: the PWA is vanilla, with no framework, no build step, no CDN and not
one inline script, so there is no `unsafe-inline` to accommodate. That same fact is what makes
the token in `localStorage` tolerable, and the two decisions are written next to each other on
purpose — **the day a third-party script arrives, both fall together.**

**Login throttling.** Five attempts per minute, keyed by origin *and* matrícula. Keyed by IP
alone it would punish a whole unit behind one NAT; by matrícula alone, someone could sweep
different accounts from the same origin without ever hitting the limit. A successful login
clears the counter — a mistake followed by a success should not leave the door primed.

**Rate limit on the AI routes.** Twenty per minute per person and origin. Each query costs
tokens and `/ai/rascunho` also creates a permit; a client stuck in a loop would fill the
archive and the bill before anyone noticed.

**Uploads are checked by content, not only by name.** The first block of every upload must
carry the signature of the type its extension promises. An executable renamed to `.pdf`
cleared the old extension allowlist and would later be served back for someone to open on
board. Verified against the running application with a real `MZ` header.

**Signing a document you did not read is refused.** A transition may carry `visto_em`; if the
permit changed after the read, it is rejected with `documento_alterado`. Optional here, unlike
on edit, and the difference is deliberate: on edit it prevents an overwrite, here it prevents
a signature standing for a document that has since changed — which the trail's document hash
would otherwise record as an agreement that never happened.

**Errors no longer leak.** An unhandled exception returns a generic `500`; the detail goes to
the log. A stack trace in a response hands over file paths, library versions and sometimes a
fragment of the query.

## Adversarial sweep (post-L13)

The L13 audit confirmed what the design intended. This pass looked for the opposite: what the
code does that the design did **not** intend. Eight defects, none of which the 232-test suite
caught, each now with a regression test that fails if the fix is removed.

| Severity | Defect | Why the suite missed it |
|---|---|---|
| **High** | The shared data cache is not scoped to a user. On a shared deck tablet, whoever logs in next could read the previous user's permits offline — the service worker keys by URL, and a URL has no owner | No test exercises two identities on one device |
| **High** | A queued offline edit was sent with whatever token was active at flush time. User A's correction could be **recorded in the trail as authored by user B** | Same |
| **High** | A condition that reappears after being resolved hit the `UNIQUE` on alert identity and crashed the sync with a `500`. Reachable path: an expired permit in execution is suspended (alert resolved) and then resumed | The tests only ever moved a condition in one direction |
| **High** | A genuine `500` lost **every** security header. Unhandled exceptions are served by `ServerErrorMiddleware`, which sits above all application middleware | The L13 test used a `401` — an `HTTPException`, which travels through the stack |
| **Medium** | The rate limiter grew without bound: 50,000 login attempts with distinct matrículas retained 50,000 keys forever, and merely *checking* a key allocated one. Unauthenticated memory exhaustion | Nothing measured memory |
| **Medium** | `AEGIS_UPLOAD_DIR=static/uploads` would have published every attachment. The rule existed only as a comment | Configuration was never tested as an input |
| **Medium** | Cache-first on the shell froze the installed app at its first version: a fix to `app.js` would never reach a tablet that had installed it, silently | No test of the update path |
| **Low** | `visto_em` without a timezone compared naive against aware and never matched, so such a client got `409` on every edit — failing closed, but for a reason its message did not state | Every test sent an offset |

**One fix was worse than the defect, and the sweep caught that too.** The first attempt at the
rate limiter swept expired keys whenever the dictionary exceeded a size threshold. With many
keys still inside the window, that meant a full pass on every attempt, freeing nothing —
trading memory exhaustion for CPU exhaustion, which arrives sooner. It hung a verification run
at 50,000 keys. The sweep is now time-based: at most one pass per window, which bounds both.

The pattern behind most of these is the same, and worth naming: **each defect sat exactly where
two mechanisms meet** — the service worker and the session, the exception handler and the
middleware stack, configuration and the static mount, the queue and identity. Tests written per
mechanism pass individually while the seam between them leaks.

## Findings

Every pendency declared in L0–L12, and what became of it. "Accepted" means the risk is real,
understood, and deliberately not fixed — with the reason, so the next person inherits the
decision rather than the surprise.

| # | Severity | Finding | Status |
|---|---|---|---|
| P3 | High | No security headers, no rate limiting, errors leaking stack traces | **Fixed** — CSP, nosniff, frame-deny, referrer, HSTS outside development; generic `500` |
| P14 | High | Login with no attempt limit; brute force unimpeded | **Fixed** — 5/min per origin+matrícula, cleared on success |
| P30 | High | Only the extension validated; a renamed executable was accepted | **Fixed** — signature check on the first block, before anything is written |
| P34 · P39 | Medium | AI routes without any usage limit; each call costs tokens, one creates a permit | **Fixed** — 20/min per person and origin |
| P47 | Medium | A transition could be signed over a stale read | **Fixed** — optional `visto_em`, refused with `documento_alterado` |
| P14b | Medium | No token revocation list; a leaked token is valid until it expires | **Accepted** — the token carries no profile and is re-read from the database on every request, so revoking a profile or deactivating an account takes effect immediately. What survives is the identity, for at most one shift. A revocation list means shared state across processes; revisit with the multi-process deploy |
| P45 | Medium | Token in `localStorage`, readable by any script on the origin | **Accepted, conditionally** — no third-party script and no CDN ship with the product, and the CSP forbids both. Moving to an httpOnly cookie means CSRF protection on every mutation; it buys nothing until the premise breaks. **The condition is the CSP: if it ever relaxes, this becomes a defect** |
| P33 | Medium | Permit text reaches the model inside tool results | **Accepted** — reviewed here. It cannot make the model act: there is no tool that writes, and the sources come from the database rather than the reply. What it can influence is the *wording* of an answer. Structural containment beats prompt hardening, and the structure is already in place |
| P16 · P26 | Low | Login is not in the trail; there is no global chain for events without a permit | **Accepted** — the chain is per permit by design, and the document is what an investigation reconstructs. A login trail is a different artifact with a different retention question, not a missing link in this one |
| P27 · P42 | Low | The verifier walks the whole chain per query; the alert sync scans everything per pass | **Accepted** — both are linear in a per-permit trail and a live-permit set that stay small at one unit's volume. They become real when the archive does |
| P29 | Low | A failed `unlink` after commit leaves an orphan file | **Accepted** — the alternative, deleting before the commit, risks a row pointing at nothing, which is worse. An orphan file is recoverable by sweep |
| P22 | Low | The API accepts naive datetimes and treats them as UTC | **Accepted** — every column normalises at the database edge (`UTCDateTime`), so the ambiguity never reaches storage. Requiring an explicit offset is an HTTP contract decision |
| P44 · P46 | Low | Transitions are not queued offline; attachments cannot be uploaded offline | **Accepted by design** — see the offline section: queueing a release would be a promise the server has not made |
| P48 | Low | No test runs the JavaScript | **Partly fixed** — the accepted mitigation ("the endpoint contracts they consume") was named but never written, and it cashed in: see P50. There is now a test matching every `api()` call in `app.js` against the live OpenAPI schema, which catches shape drift without a JS runner. What still has no coverage is behaviour — rendering, routing, the offline queue. Adding a runner remains a build-step decision the project has avoided on purpose |
| P49 | High | **The audit chain forks under concurrent writes.** `registrar_evento` reads the last link and then inserts, with no lock, constraint or isolation level between the two. Two simultaneous events on the same permit — an attachment and a signature in the same moment — read the same `hash_anterior` and are born siblings. The chain forks and the verifier reports tampering forever, on a trail nobody touched. SQLite hides this behind its global write lock; the production PostgreSQL does not | **Fixed** — `UNIQUE (pt_id, hash_anterior)`. The loser of the race gets an `IntegrityError` and its request fails, which is loud but honest: better a repeated submission than a trail that accuses itself. Retrying belongs to the whole request, not to the writer — after an `IntegrityError` the transaction is already lost |
| P50 | Medium | **The rule engine's verdict never reached the screen.** `GET /pts/{id}/pendencias` returns the whole evaluation (`AvaliacaoRead`); the detail screen iterated the response directly, so `.length` was `undefined`, `for...of` threw on the object, and the `catch` turned it into an amber notice that looked like a network problem. Every permit, every session, since L4 | **Fixed** — the response is destructured. Found by running the application, not by the suite; guarded now by the contract test in P48 |
| P41 | Medium | Nothing schedules the alert sync | **Fixed** — `python -m app.sincronizar_alertas`, a command a scheduler knows how to call, with the crontab and `schtasks` lines in its own docstring and in the README. It goes to the database rather than to `POST /alertas/sincronizar` on purpose: that route is restricted to coordination and the OIM, so a scheduler calling it would need a service credential stored, rotated and eventually leaked — a machine account with write powers invented to solve scheduling. A test covers the entrypoint, because wiring is what fails silently on a server |
| P51 | Low | The suite is intermittent on Windows: one full run in three ended with a fixture `ERROR` in `test_alertas.py` that passes in isolation and in the other runs | **Open** — the `db` fixture does `create_all`/`drop_all` against one shared `test_aegis.db` per test, and the file stays open in the pool between them. An in-memory or per-test file database would remove the shared resource. Not reproduced on demand yet, and CI on Linux has not shown it |
| P40 | — | An `indicadores` tool for the AI conflicts with how rule 3 is implemented | **Open — product decision** |
| P37 | — | A draft cannot be born incomplete | **Open — product decision** |

Two limits apply to the whole table. The rate limiters are **in-process**: with more than one
worker each counts separately, so the effective limit multiplies by the worker count — a floor,
not a ceiling, and the place for a real one is the edge. And no penetration test has been run;
this is a code and design audit by the person who wrote the code, which is worth exactly what
that is worth.
