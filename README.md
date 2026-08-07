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
[![Status: L3 of L13](https://img.shields.io/badge/status-L3_of_L13-f59e0b.svg)](#roadmap)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Offline capable](https://img.shields.io/badge/PWA-offline_planned-0ea5e9.svg)](#offshore-constraints)

</div>

---

## Current state — read this before cloning

**L0 through L3 are done.** What runs today: the thirteen-table data model with its migrations,
Argon2id login issuing a JWT session, role-based authorization with a per-unit scope applied
inside the query, and the permit itself — created, listed, read and corrected while it is still a
draft, with a form whose fields are defined per work type and validated by deterministic rules.

**What is not there yet is the part that makes a permit a permit.** There is no state machine, so
a draft cannot advance; no electronic signature; no audit trail; no rule engine deciding whether
the work is safe to release; and no AI. Those are L4 through L10.

So: you can issue a draft and query it. You cannot approve, release or close anything, and
nothing here yet blocks an expired certificate. If you cloned this expecting a working permit
system, come back when the roadmap below has more green in it.

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

```powershell
python -m alembic upgrade head
python -m app.seed
python -m uvicorn app.main:app --reload
```

The PWA shell is at <http://127.0.0.1:8000>, the interactive API docs at `/docs`.

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

Forty-nine tests. The ones worth naming are the ones that would fail loudly if a guarantee
quietly stopped holding: SQLite foreign keys are actually enforced; the migration is compared
against the models and then rolled all the way back; a forged `alg: none` token is rejected;
deactivating a user cuts access before their token expires; a permit outside your scope answers
`404`; and the server ignores `estado`, `numero` and `requisitante_id` when a client sends them.

They need no `.env` — the fixtures set the environment before importing the application, which is
also how CI runs them, on 3.11 and 3.14.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness plus a real `SELECT 1` against the database |
| `POST` | `/auth/login` | Matrícula and password for a bearer token |
| `GET` | `/auth/eu` | Who is authenticated, and which units they reach |
| `GET` | `/pts/modelos/{tipo_trabalho}` | Form definition for a work type |
| `POST` | `/pts` | Opens a permit in `RASCUNHO` |
| `GET` | `/pts` · `/pts/{id}` | Listing and detail, scoped in the query |
| `PATCH` | `/pts/{id}` | Corrects a permit while it is still a draft |
| `GET` | `/` · `/static/{path}` | PWA shell and vendored assets |

A blocking pendency returns `409` with a structured list — `codigo`, `severidade`, `mensagem`,
`campo` — never a bare sentence, because the screen needs to know which field to mark. `422`
still means the payload did not parse at all.

Still scheduled: transitions and signatures at L5, the audit trail at L6, attachments at L7,
search and dossier export at L8, the AI endpoints at L9 and L10, indicators and alerts at L11.

## Roadmap

**L0 — done.** Bootstrap: structure, settings, database, health check, Alembic, PWA shell.

**L1 — done.** Thirteen tables, the initial migration, Pydantic schemas and an idempotent seed.

**L2 — done.** Argon2id passwords, JWT sessions lasting one shift, role-based authorization and a
per-unit scope that fails closed.

**L3 — done.** Permit CRUD while in draft, a dynamic form per work type validated by deterministic
rules, and scope applied inside the query rather than to the result. Field-by-field versioning
belongs to the state machine and moved to L5 — a draft being typed is not a revision.

**L4–L6 — the controls.** The deterministic rule engine (missing document, expired certification,
validity shorter than declared duration, incompatible simultaneous permits, hot work coinciding
with confined space in the same area), the state machine with electronic signatures, and the
hash-chained append-only audit trail with an integrity verifier.

**L7–L8 — the archive.** Attachments with expiry and hashing, OCR ingestion of legacy scans,
combined structured search, dossier export.

**L9–L10 — the assistant.** Natural-language search over read-only tools scoped to the
authenticated user, and draft generation that explicitly flags every field still requiring a human
decision.

**L11–L13 — operation.** Indicators and escalating alerts, the offline PWA with conflict
resolution, and a closing security audit.

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
