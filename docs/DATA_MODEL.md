# Data model

Implemented in L1. Thirteen tables, one Alembic revision, and a seed for development.
Source of truth is `app/models/`; this page explains the decisions behind it.

## Tables

| Table | Purpose |
|---|---|
| `usuario` | matrícula, nome, e-mail, empresa, cargo, perfil, ativo |
| `unidade` | platform or vessel, with its operational identifier |
| `area` | belongs to a unidade; `codigo` unique per unidade, not globally |
| `equipamento` | TAG, description, area, criticality |
| `certificacao` | user, type (NR-33, NR-34, NR-35, NR-10, ANAC-RPAS), issue and expiry |
| `modelo_pt` | approved template per work type, with checklist and field definitions |
| `permissao_trabalho` | the permit: uuid, number, work type, unit, area, equipment, description, validity window, state, version, requester, hazards, controls, answers |
| `pt_equipe` | crew allocated to a permit — the path L4 uses to reach each member's certifications |
| `pt_versao` | full snapshot plus field-by-field diff, author and reason |
| `anexo` | APR, ASO, certificate, report, photo, sketch — with expiry and SHA-256 |
| `assinatura` | permit, user, signing role, permit version, timestamp, document hash |
| `audit_event` | append-only: actor, role, event type, source and target state, reason, timestamp, device, IP, geolocation, document hash, previous hash, event hash |
| `alerta` | type, target entity, deadline, escalation level, status |

## Profiles (`perfil`)

`requisitante`, `executante`, `tecnico_seguranca`, `area_responsavel`, `coordenador`,
`oim`, `auditor`, `admin`. Defined in `app/models/enums.py`; the RBAC that uses them is L2.

## Permit states

```
RASCUNHO → VALIDACAO → ANALISE_SMS → APROVACAO → LIBERACAO → EM_EXECUCAO → ENCERRADA → ARQUIVADA
```

Deviations: `SUSPENSA` (only from `EM_EXECUCAO`) and `REJEITADA` (returns to `RASCUNHO`).
L1 ships the vocabulary only — the state machine that forbids skipping is L5.

## Decisions worth knowing

**Enums are portable, not native.** `enum_col()` in `app/models/tipos.py` builds
`VARCHAR + named CHECK`, identical on SQLite and PostgreSQL, and stores the member *value*
via `values_callable`. Without it SQLAlchemy stores the member *name*, and the database
would say `NR_35` where the norm, the API and the screen all say `NR-35`.

**`tipo_evento` and `alerta.tipo` are free text.** Both catalogues grow with every loop;
a CHECK constraint would demand a migration for each new audited event.

**Integer primary keys, plus a `uuid` on `permissao_trabalho` alone.** L12 creates permits
offline: autoincrement ids generated on two tablets collide on sync, and renumbering a
permit that already circulated is not an option. One column now, no renumbering later.

**Constraints are named** through `NAMING_CONVENTION` on `Base.metadata`. SQLite has no
full `ALTER TABLE`, so Alembic recreates tables in batch mode — and an anonymous constraint
does not survive the recreation.

**`audit_event.pt_id` uses `ON DELETE RESTRICT`.** Deleting a permit that already has a
trail would delete the evidence with it. The database refuses; there is a test for it.

**Signatures are unique per (permit, role, permit version).** Revising the document
invalidates previous signatures, and signing again is a new row — never an update.

## Integrity rules

- `audit_event` accepts inserts only. A correction is a new compensating event pointing at
  the original through `evento_compensado_id`. The append-only enforcement itself is L6.
- `hash_evento = H(hash_anterior + payload)` forms a chain per permit — columns exist, the
  chain and its verifier are L6.
- Foreign keys are enforced on SQLite through `PRAGMA foreign_keys=ON`, set on every
  connection in `app/database.py`.

## Seed

`python -m app.seed` creates 1 unidade, 3 áreas, 5 usuários, 2 equipamentos and 4
certificações — one of them **expired on purpose**, so L4 has a real case to block at
release time. It is idempotent (each row is looked up by its natural key first) and its
dates are relative to today, because a seed with fixed dates rots into showing everything
as expired.
