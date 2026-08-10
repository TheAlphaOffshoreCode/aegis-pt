<div align="center">

# AEGIS PT

**Work permit management for offshore units — the AI reads and drafts, it never authorizes.**

A Work Permit is the document that lets anyone do something dangerous on a platform: hot work,
confined space entry, work at height, lifting, electrical intervention, drone inspection. Today
it is paper on a clipboard, scanned into a network folder nobody can query. This turns that
cycle into a dynamic form, a signed approval chain, a searchable archive, and a hash-chained
audit trail that survives an incident investigation.

[![CI](https://github.com/TheAlphaOffshoreCode/aegis-pt/actions/workflows/ci.yml/badge.svg)](https://github.com/TheAlphaOffshoreCode/aegis-pt/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Status: L13 of L13 — complete](https://img.shields.io/badge/status-L13_of_L13_complete-22c55e.svg)](#roadmap)
[![Tests: 270](https://img.shields.io/badge/tests-270_passing-22c55e.svg)](#tests)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Offline capable](https://img.shields.io/badge/PWA-offline_reads-0ea5e9.svg)](#offshore-constraints)

</div>

---

## Current state — read this before cloning

**All thirteen loops are done, and the permit cycle actually closes.** A permit is opened from a
form defined per work type, collects its documents, walks the approval chain gathering a
signature at each step, gets checked by a deterministic rule engine before release, leaves a
hash-chained trail that detects tampering, and can be pulled back out as a single dossier —
data, versions, signatures, attachments, trail, and whether that trail still verifies.

The clearest way to say what works is to show it refusing to work. This is a real run against
the development database:

```text
criada: 201 PT-2026-0002 RASCUNHO
  10001 -> VALIDACAO: OK      10004 -> ANALISE_SMS: OK
  10003 -> APROVACAO: OK      10005 -> LIBERACAO: OK
  10002 -> EM_EXECUCAO: 409 BARRADO
      certificacao_vencida: NR-35 de Rafael Souza vence em 23/06/2026,
                            antes do fim da janela da PT
```

Four signatures collected, five roles involved, and the release refused because one worker's
NR-35 expires before the permit's own window closes — decided by tested code, not by anyone
remembering to look.

Since L9 it also answers questions in plain Portuguese — and the interesting part is what it
refuses to do. The model reaches three tools, all of which only read, so there is no technical
path by which any prompt approves or releases anything. Every deadline in an answer was
computed by the rule engine, not by the model. And the sources are collected from what the
database returned, never parsed out of the reply, so an answer with no retrieved permit is
replaced with "não encontrei" in code rather than trusted to say so. The contract:

```text
POST /ai/consulta   {"pergunta": "Quais PTs de trabalho a quente estão abertas?"}

{ "resposta": "Uma: PT-2026-0001, solda em suporte de tubulação, ainda em rascunho.",
  "fontes": ["PT-2026-0001"] }
```

`fontes` lists what the tools read, and the same question asked by someone posted to another
unit retrieves nothing — the scope enters the query before the model sees a single row. Both
of those are covered by tests that run without a network or an API key.

**The model can be a local one.** Point `AEGIS_AI_BASE_URL` at an Ollama server and the same
loop, the same tools and the same guarantees run against a model on the vessel's own hardware —
no link, no API key, and no permit content leaving the unit. That is the offshore case rather
than a cost optimisation: the satellite link is expensive, intermittent and sometimes absent.

Swapping the model is safe here precisely because none of the eight rules depend on which model
answers. No tool writes, so a weaker model still cannot approve a permit; safety numbers come
from the rule engine; and the sources are collected from what the database returned, so a
hallucinated permit number gets the whole answer discarded rather than delivered. A weaker model
answers worse — it does not answer with more authority. Verified end to end against `gemma4:8b`:
both permits retrieved and cited, and a draft generated with the form answers passed through
untouched by the model.

Since L10 it also drafts. `POST /ai/rascunho` takes a sentence — *"preciso soldar um suporte
de tubulação no convés principal"* — and returns a permit in `RASCUNHO` with the work type
identified, the hazards and controls written from what this unit actually did before, and the
sources cited. What makes it safe is the division of labour, which is the API contract rather
than a convention: **every measurement and every deadline arrives in the request, from a
person, and is never shown to the model.** A gas reading comes off a calibrated detector.
There is nothing for a language model to contribute to it, and a plausible-looking number
there is the exact failure this is built to prevent.

The permit is then created by the same service call as any other — same validation, same
numbering, same trail, same signature chain ahead of it. Proposing is not approving. The
trail records it as `pt.criada_por_ia`, so an AI-drafted permit stays identifiable years
later, in the investigation where it matters.

L11 added the board: `GET /indicadores` counts the operation and `GET /alertas` lists what is
going wrong, escalating from requisitante to coordenador to OIM as deadlines pass. An alert is
**resolved, never deleted** — a problem that disappears without trace is exactly what an
investigation later needs to find. And escalation is a function of the clock rather than a
counter, so running the sync more often cannot inflate the urgency of anything.

L12 turned it into something you can actually use on a deck. Real screens — login, the permit
list, issuing a permit, a permit with its dynamic form, attachments and available steps, the
board — installable, dark, and readable offline. The identity fonts are vendored rather than fetched: a font that only loads
online is an identity that disappears exactly offshore.

The part worth explaining is the sync, because it is where an offline app usually lies. Every
draft edit carries `visto_em` — the timestamp the client read before editing. If the permit
moved on while the tablet was out of signal, the late edit is **refused**, not merged and not
applied on top:

```text
PATCH /pts/1   { "descricao": "Corrigida no convés", "visto_em": "…12:42:08" }

409  edicao_desatualizada
     "A PT foi alterada em 08/08/2026 04:09:14 UTC, depois da versão que você editou.
      Recarregue e refaça a correção."
```

Reading works offline; **signing a step does not, deliberately.** The rule engine decides at
the instant of the transition, so queueing a release would let someone walk away from the
screen believing they had authorised work the server may still refuse. The screen says so
rather than hiding it.

L13 closed the contract by settling its debts rather than adding features. Security headers on
every response including errors, login throttled at five attempts a minute, the AI routes at
twenty, uploads checked by content instead of by filename — an executable renamed to `.pdf`
cleared the old extension allowlist — and a signature refused when the document changed after
it was read. Everything else is in the Findings table of [docs/SECURITY.md](docs/SECURITY.md):
**every pendency declared across the thirteen loops resolved into a fix with a test behind it,
or a risk accepted in writing with its reason.**

Two of those are worth repeating here, because they are conditions rather than conclusions. The
token lives in `localStorage`, which is only defensible because no third-party script ships and
the CSP forbids one — **relax `script-src` and it becomes a defect.** And the rate limiters are
in-process: with more than one worker the effective limit multiplies, so the number is a floor,
not a ceiling.

Then a sweep looked for the opposite of what the audit had confirmed: not whether the design
holds, but what the code does that the design never intended. **It found eight defects, none of
which the 232-test suite caught** — four of them serious. The shared data cache was not scoped
to a user, so on a shared deck tablet the next person to log in could read the previous one's
permits offline. A queued offline edit went out with whatever token was active at flush time,
which could record user A's correction in the trail **as authored by user B**. An alert
condition that reappeared after being resolved crashed the sync with a `500`. And a genuine
`500` lost every security header, because unhandled exceptions are served above all application
middleware — the test that supposedly proved otherwise used a `401`, which travels through the
stack. Testing the similar path is not testing the path.

Nearly all of them sat in the same kind of place: **the seam between two mechanisms** — the
service worker and the session, the error handler and the middleware stack, configuration and
the static mount, the queue and identity. Tests written per mechanism pass individually while
the join between them leaks. Worth knowing where to look next time.

One fix turned out worse than the defect it replaced, and only surfaced because the fix itself
was measured rather than assumed: the first rate-limiter repair swept expired keys by dictionary
size, which with many live keys means a full pass per request that frees nothing — trading
memory exhaustion for CPU exhaustion, which arrives sooner. Every one of the eight now has a
regression test, each verified to fail when its fix is reverted.

The trail has a screen of its own now, which matters more than it sounds: a hash chain nobody
can look at is a promise, not evidence. Every permit carries a collapsed **Trilha de auditoria**
panel that states the verdict in words — `cadeia íntegra · N elos`, or where exactly it stopped
closing — and lists each link with its timestamp, actor role, state change and the two ends of
its hash. It loads only when opened: history is not what anyone reads to decide something now,
and it is the longest answer this screen can ask for over a shipboard link.

**What is still missing:** ingestion of the paper archive with OCR (proposed as its own loop —
what it actually needs is a bulk import flow, not an OCR call), two product decisions listed in
`LOOP_STATE.md`, and screens for the dossier, the version history, compensating events and both
AI routes — all of which work over the API and none of which a deck tablet can reach yet. No
penetration test has been run; this is a code and design audit by the person who wrote the code,
and it is worth exactly what that is worth.

## The problem

An offshore unit issues dozens of work permits a day, and every one of them is paper. A permit is
filled in by hand, walked around the platform for four or five signatures, scanned at the end of
the shift, and filed. The consequences are all the same shape: nobody can answer "is there hot
work open in the process area right now?" without walking there, an expired NR-33 certificate is
caught only if someone remembers to look, and after an incident the investigation depends on a
box of scans nobody can search.

The paperwork is not the safety measure. The paperwork is what happens *instead* of the safety
measure once the volume gets high enough.

## The golden rule

> **The language model reads and drafts. It never authorizes, and it never produces a number
> anyone might act on.**

There is no technical path by which the model approves, releases or closes a permit — every tool
it can reach is read-only or draft-creating, and the write side of the workflow is not exposed to
it at all. Separately, no safety-relevant number ever comes out of it: distances, loads,
durations, counts and expiry dates are computed by the deterministic rule engine and tested.

This split is the whole design. A model that summarizes ten archived permits and gets the tone
slightly wrong costs nothing. A model that says a certificate is valid, or that a permit window
covers the declared duration, has just replaced a control with a guess.

Every AI answer also cites the permits it read. If nothing was retrieved, the answer is "não
encontrei" — never a plausible reconstruction.

## What it will do

| Pillar | Substance |
| --- | --- |
| Intelligent issuance | Form fields vary by work type, prefilled from the registry and the crew's last comparable permit |
| Digital approval | Role-based flow, electronic signature, advance blocked by any blocking pendency |
| Central repository | One archive, versioned attachments, OCR over the legacy scans |
| AI assistant | Natural-language search and draft generation, always with cited sources |
| Control and alerts | Deterministic rule engine, inconsistency detection, expiry alerts with escalation |
| Audit and integration | Hash-chained append-only trail, dossier export, public API |

The permit moves through a state machine, and no step can be skipped:

```text
RASCUNHO → VALIDACAO → ANALISE_SMS → APROVACAO → LIBERACAO → EM_EXECUCAO → ENCERRADA → ARQUIVADA
```

with `SUSPENSA` reachable only from `EM_EXECUCAO`, and `REJEITADA` returning to `RASCUNHO`.
Every transition records actor, role, timestamp, device, IP, geolocation and document hash.

## How it is built

In **numbered loops, L0 to L13**, one at a time, each with a closed scope and an objective
acceptance criterion. A loop ends with a report and a full stop — nothing advances until the
previous loop's criterion actually passes. `LOOP_STATE.md` is the resume point and carries every
declared pendency, so an unfinished thing is written down rather than forgotten.

The reason for the ceremony is that this is safety software. A feature half-built in a codebase
like this is not a rough edge; it is a control somebody believes exists.

## Offshore constraints

Decisions that come from where this runs, not from taste:

- **The PWA has to work with no connectivity.** A platform's satellite link drops, and a permit
  still needs to be consulted and a checklist still needs to be signed. Reads are cache-first and
  writes queue for sync — and a conflict on reconnect is presented for a human decision, never
  resolved by silently overwriting.
- **No CDN, ever.** Charts and fonts will be vendored into the repository — an external request
  is a blank screen on a bad link. The rule is binding from the start; the vendoring itself
  happens when the real screens do, at L11–L12. Today the shell falls back to system fonts.
- **SQLite in development, PostgreSQL in production, same code.** Only the URL changes.
- **Portuguese domain vocabulary.** The entities are named after the regulatory documents the
  platform enforces — NR-33, NR-34, NR-35, NR-10 — because a translated `work_permit` table is a
  translation error waiting to happen in an audit.

## Running it

Windows / PowerShell, one command per line, from the project root.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into `AEGIS_SECRET_KEY` in `.env`. The application refuses to start
without a secret of at least 32 characters — a development fallback secret is precisely how a
weak key reaches production.

`AEGIS_ANTHROPIC_API_KEY` is optional and enables `POST /ai/consulta`. It is read in the
backend only, never sent to the browser, and `.env` is gitignored. Without it everything else
runs and that one route answers `503`.

For a local model instead, set `AEGIS_AI_BASE_URL=http://localhost:11434` and
`AEGIS_AI_MODELO` to the Ollama model name — one that supports tools, or the loop has nothing
to call. The key is then unused. Two knobs exist because the development machine needed them,
and both are commented in `.env.example`: `AEGIS_AI_LOCAL_NUM_GPU` pins how many layers go to
the GPU (automatic splitting across two small cards crashes the ggml scheduler), and
`AEGIS_AI_LOCAL_PENSAR` keeps the model's reasoning on, which is what makes a small model call
the tools at all instead of answering with a question.

```powershell
python -m alembic upgrade head
python -m app.seed
python -m uvicorn app.main:app --reload
```

The PWA shell is at <http://127.0.0.1:8000>, the interactive API docs at `/docs`.

Alerts are materialised by an explicit pass, never by a hidden daemon, so **something has to
call it on a schedule** or the board quietly ages:

```powershell
python -m app.sincronizar_alertas
```

```cron
# Linux, every five minutes
*/5 * * * * cd /srv/aegis-pt && .venv/bin/python -m app.sincronizar_alertas >> /var/log/aegis-alertas.log 2>&1
```

The command runs against the database directly rather than calling `POST /alertas/sincronizar`,
which stays for the button on the screen. The route is restricted to coordination and the OIM,
so a scheduler would need a service credential stored on the server, rotated and eventually
leaked — a machine account with write powers, invented to solve scheduling. The command is
already inside the database and needs none. It is idempotent, so a missed run is recovered by
the next one, and it fails loudly: an unhandled exception is a non-zero exit, which is what
makes the scheduler complain instead of the board silently stopping.

The seed creates one unit, three areas, five users, two pieces of equipment, two permit templates
and four certifications — **one of them deliberately expired**, so the rule engine has a real case
to block once L4 exists. Development accounts are matrículas `10001` to `10005`, password
`aegis-dev-2026`. It refuses to run outside `environment=development`, and the guard sits inside
the seeding function rather than only in `__main__`, because importing it is just as effective a
way to create accounts with a known password.

### Tests

```powershell
python -m pytest -q
```

Two hundred and seventy tests, none of which reach the network — the AI loop is exercised
with an injected client, and the suite forces the API key, the local model URL and the model
name to fixed values, so nothing in a developer's `.env` can make the tests call out, bill, or
assert what that machine happens to have installed. The ones worth naming are those
that fail loudly the day a guarantee quietly stops holding:

- the audit chain **detects tampering** — a row edited through raw SQL, bypassing the
  application entirely, is caught, and the ORM refuses the same edit outright;
- an expired certificate **blocks release**, and the issuer **cannot sign their own permit**;
- skipping a step in the flow is rejected, because the transition does not exist;
- a forged `alg: none` token is refused, and deactivating a user cuts access before their
  token expires;
- an event sealed under an older payload format still verifies — adding a field must not
  invalidate the trail written yesterday;
- an upload named `../../etc/passwd.pdf` is stored as `passwd.pdf`, an `.html` upload is
  refused outright, and every download comes back as `attachment` with `nosniff`;
- a paginated search filtered to a unit outside your scope returns empty — and its `total`
  says zero, because a count over a wider universe leaks how much exists beyond your reach;
- a permit outside your scope answers `404`, and the server ignores `estado`, `numero` and
  `requisitante_id` when a client sends them;
- an AI answer that cites a permit the tools never read keeps that number out of `fontes` —
  and an answer with no source at all is thrown away and replaced, because the citation
  guarantee cannot depend on the model remembering to cite;
- the same scripted conversation run as two users on different units retrieves different
  permits, and the AI tool set itself is asserted, so a fourth tool fails the suite until
  someone has proven it only reads;
- an AI-drafted permit stores the gas reading exactly as the caller sent it, and that value
  appears nowhere in the request sent to the model — the proposal schema has no field it
  could come back in;
- running the alert sync twice in the same minute opens nothing and escalates nothing, and an
  alert whose condition disappears is marked resolved rather than deleted;
- **an edit made offline never overwrites a change that arrived first** — the late write is
  refused, the earlier correction survives, and reloading is the way forward;
- an alert condition that disappears and comes back **reopens the same row** instead of
  crashing on the uniqueness of alert identity, and a real unhandled exception still carries
  every security header;
- SQLite foreign keys are actually enforced, and the migration is compared against the models
  and then rolled all the way back;
- **two events cannot chain off the same link** — a `UNIQUE (pt_id, hash_anterior)` refuses the
  fork that two simultaneous writes would otherwise leave behind, which the verifier would then
  report as tampering forever;
- **the screens are checked against the shapes the endpoints actually return** — every `api()`
  call in `app.js` is matched against the live OpenAPI schema, so a response consumed as a list
  when it is an object fails the suite instead of the screen;
- **areas are scoped like everything else**, and **deactivating a form model removes its work
  type from the issue screen** — a type with no model would be a dead end the screen offers
  anyway;
- **the shell is always revalidated** — `/`, `/static/*` and `/sw.js` ship `Cache-Control:
  no-cache`, and the `304` carries it too, so the browser can never fall back to heuristic
  freshness and serve a new `index.html` beside a cached old `app.js`;
- **the service worker's version follows the shell's content** — the version is a digest of the
  static files rather than a string someone remembers to bump, so a changed file cannot reach a
  tablet as a new `index.html` sitting next to a cached old `app.js`;
- **the scheduled command actually runs a pass** — `python -m app.sincronizar_alertas` is what
  the crontab line calls, and entrypoint wiring is precisely what breaks in silence: the import
  goes wrong on the server, the board stops, and nothing on any screen says it stopped;
- **a validation error reaches the screen with text in it** — `409` carries the rule engine's
  `mensagem`, `422` carries Pydantic's `msg`, and while the screen only knew the first the red
  box came up empty on something as ordinary as an inverted validity window.

Thirty-seven of them touch no database at all — the rule engine, the state machine and the form
validator are pure functions, and those thirty-seven run in **0.07 s** against roughly forty-five
seconds for the full suite. That gap is the point: a safety rule that is expensive to test ends
up under-tested.

They need no `.env` — the fixtures set the environment before importing the application, which is
also how CI runs them, on 3.11 and 3.14.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness plus a real `SELECT 1` against the database |
| `POST` | `/auth/login` | Matrícula and password for a bearer token |
| `GET` | `/auth/eu` | Who is authenticated, and which units they reach |
| `GET` | `/areas` | Operational areas in scope — what the issue screen picks from |
| `GET` | `/pts/modelos` | One active model per work type; the type selector's only source |
| `GET` | `/pts/modelos/{tipo_trabalho}` | Form definition for a work type |
| `POST` | `/pts` | Opens a permit in `RASCUNHO` |
| `GET` | `/pts` | Structured search, paginated, scoped in query **and** count |
| `GET` | `/pts/{id}` · `/pts/{id}/versoes` | Detail, and version history with diffs |
| `GET` | `/pts/{id}/dossie` | The whole permit in one document, integrity included |
| `PATCH` | `/pts/{id}` | Corrects a permit while it is still a draft |
| `GET` | `/pts/{id}/pendencias` | The rule engine's verdict — a query, never a decision |
| `GET` · `POST` | `/pts/{id}/transicoes` | Available steps, and moving through them |
| `GET` | `/pts/{id}/trilha` | The audit trail, already verified link by link |
| `POST` | `/pts/{id}/trilha/{evento_id}/compensacao` | Corrects a record without rewriting it |
| `POST` · `GET` · `DELETE` | `/pts/{id}/anexos` | Documents, hashed server-side on upload |
| `GET` | `/pts/{id}/anexos/{id}/conteudo` | Download, always `attachment` + `nosniff` |
| `POST` | `/ai/consulta` | Natural-language question, answered with the permits it read |
| `POST` | `/ai/rascunho` | Drafts a permit from a description; measurements come from you |
| `GET` | `/indicadores` | The operation in counts — every value a `COUNT`, never an estimate |
| `GET` · `POST` | `/alertas` · `/alertas/sincronizar` | What is going wrong, and who it has escalated to |
| `GET` | `/` · `/static/{path}` · `/sw.js` | PWA shell, vendored assets, service worker |

A blocking pendency returns `409` with a structured list — `codigo`, `severidade`, `mensagem`,
`campo`, `responsavel` — never a bare sentence, because the screen needs to know which field to
mark and who is expected to resolve it. `422` still means the payload did not parse at all.

Every route above exists and is tested. Not all of them have a screen yet: the dossier, the
version history, compensating events and the two AI routes are reachable over the API only,
and that gap is listed in `LOOP_STATE.md` rather than left for someone to discover.

The `/ai/*` routes answer `503` when no API key is configured. The AI degrades on its own; the
rest of the application starts and works without it.

## Roadmap

**L0 — done.** Bootstrap: structure, settings, database, health check, Alembic, PWA shell.

**L1 — done.** Thirteen tables, the initial migration, Pydantic schemas and an idempotent seed.

**L2 — done.** Argon2id passwords, JWT sessions lasting one shift, role-based authorization and a
per-unit scope that fails closed.

**L3 — done.** Permit CRUD while in draft, a dynamic form per work type validated by deterministic
rules, and scope applied inside the query rather than to the result. Field-by-field versioning
belongs to the state machine and moved to L5 — a draft being typed is not a revision.

**L4 — done.** The deterministic rule engine: expired certification, window longer than the
type allows, declared duration exceeding the window, missing or expired documents, and
incompatible work sharing an area at overlapping times. Requirements live as data in
`app/rules/exigencias.py`, readable by someone who knows safety and not Python.

**L5 — done.** The state machine, with a signature per step, versioning on leaving the draft
and a chained trail entry for every transition. Skipping a step is not rejected by a check —
the transition simply does not exist in the graph.

**L6 — done.** Tamper-detecting verifier, append-only enforced by the ORM, trail API and
compensating events. The payload format is versioned, so adding a field never invalidates a
trail already sealed.

**L7 — done.** Attachments: SHA-256 computed server-side, extension allowlist, size cap enforced
mid-read, downloads served as `attachment` with `nosniff`, and removal only while the permit is
still a draft. **OCR was deliberately deferred** — it needs Tesseract as a system dependency and
a bulk-import flow for the paper archive that does not exist yet. Building it now would be
building the part nobody calls.

**L8 — done.** Structured search with eleven combinable filters and paging, version history with
field-by-field diffs, and the dossier: the permit, its versions, signatures, attachments, crew,
audit trail and the rule engine's current verdict, in one document. The integrity flag ships
with it — a history that cannot say whether it was tampered with is not evidence.

**L9 — done.** Natural-language search: three read-only tools, the user's scope applied inside
the query before the model sees anything, and citation enforced in code rather than requested
in a prompt. The sources returned are the permits the tools actually read, so an answer
grounded in nothing is replaced with "não encontrei" instead of being trusted to admit it. The
API key is read in the backend only, and its absence takes down the AI routes alone.

**Next — the archive.** Ingesting the paper archive (bulk import, OCR, indexing) is proposed as
its own loop rather than an appendix: what it needs is the import flow, and the OCR call is the
small part. After L9 it lands as one more read-only tool.

**L10 — done.** Draft generation. The assistant writes the *text* of a permit — work type,
description, hazards, controls — and fills in no form field at all: those are measurements and
attestations, taken with an instrument by someone who walked there. The proposal schema has
five fields and `additionalProperties: false`, so there is no shape in which a gas reading
could come back from the model. The draft is then created like any other, and the trail
records that an AI wrote it. Proposing is not approving, and rule 1 did not bend for
convenience — when the first design collided with the rule that a permit cannot be created
incomplete, the fix was to make the division of labour explicit in the contract, not to give
the AI a way around validation that a person doesn't have.

**L11 — done.** Indicators and escalating alerts. Every indicator is a `COUNT` scoped to the
caller — a dashboard looks harmless until someone plans a shift from it. Alerts are derived
from conditions and materialised by an explicit, idempotent sync call rather than a hidden
daemon: nothing fires on its own, so a deployment that forgets the cron gets a stale board
instead of a wrong one. They escalate by the clock, from requisitante to coordenador to OIM,
and are resolved rather than deleted. The suite passed on the first run; the development
database still found a defect, announcing an already-expired certificate as "about to expire".

**L12 — done.** The PWA: real screens, installable, dark, readable without signal, with the
identity fonts vendored rather than fetched. Draft edits made offline queue and carry what
they saw, so a late write is refused instead of silently winning; signing a step requires
connectivity, because the rule engine decides at the moment of the transition and a queued
release would be a promise the server has not made. `/impeccable audit` ran over the screens
and its findings were fixed — the ones that mattered improved accessibility rather than only
satisfying the detector.

**L13 — done.** The close. Security headers, login and AI-route rate limiting, magic-byte
checks on uploads, refusal to sign a document that changed after it was read, and errors that
no longer leak a stack trace. Then the audit itself: seventeen pendencies, each resolved into a
fix with a test or an accepted risk with its reason — including the ones deliberately *not*
fixed, because a risk somebody inherits with the reasoning attached is worth more than a
surprise.

## Disclaimer

A management tool, not a safety authority. It does not replace the judgement of the permit
issuer, the safety technician or the offshore installation manager, and no output of it — least
of all one produced by a language model — constitutes authorization to perform work.

## License

MIT — see [LICENSE](./LICENSE).

---

<div align="center">

William Oliveira · The Alpha Offshore Code

</div>
