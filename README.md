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
[![Status: L0 of L13](https://img.shields.io/badge/status-L0_of_L13-f59e0b.svg)](#roadmap)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Offline capable](https://img.shields.io/badge/PWA-offline_planned-0ea5e9.svg)](#offshore-constraints)

</div>

---

## Current state — read this before cloning

**Only L0 is done: the bootstrap.** What runs today is a FastAPI application with a health check
that also verifies the database, an initialized Alembic environment, and a diagnostic PWA shell.
That is genuinely all of it.

There are **no permits, no users, no authentication and no AI yet** — those are L1 through L10.
If you cloned this expecting a working permit system, come back after the roadmap below has more
green in it. What the repository does give you right now is the full specification, the
architectural constraints, and a foundation whose guarantees are tested rather than asserted.

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
- **No CDN.** Chart.js and the fonts are served from the repository. An external request is a
  blank screen on a bad link.
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
python -m uvicorn app.main:app --reload
```

The PWA shell is at <http://127.0.0.1:8000>, the interactive API docs at `/docs`.

### Tests

```powershell
python -m pytest -q
```

Five tests so far, covering the health check including database connectivity, the OpenAPI
contract, the PWA shell, the refusal to start on a short secret, and that SQLite foreign keys are
actually enforced. They need no `.env` — the fixtures set the environment before importing the
application, which is also how CI runs them.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness plus a real `SELECT 1` against the database |
| `GET` | `/` | PWA shell |
| `GET` | `/static/{path}` | Vendored assets |

Everything else is scheduled — `/auth` at L2, `/pts` at L3, transitions and signatures at L5, the
audit trail at L6, attachments at L7, search and dossier export at L8, the AI endpoints at L9 and
L10, indicators and alerts at L11.

## Roadmap

**L0 — done.** Bootstrap: structure, settings, database, health check, Alembic, PWA shell.

**L1–L3 — the record.** Data model and migrations, JWT authentication with granular RBAC, permit
CRUD with a dynamic form per work type and field-by-field versioning.

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
