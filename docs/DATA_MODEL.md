# Data model

Target model for L1. Nothing here is implemented yet — L0 delivered only the declarative
`Base`, the engine and the Alembic environment.

## Entities

| Entity | Purpose |
|---|---|
| `usuario` | matrícula, nome, e-mail, empresa, cargo, perfil, ativo |
| `unidade` | platform or vessel, with its operational identifier |
| `area` | belongs to a unidade |
| `equipamento` | tag, description, area, criticality |
| `certificacao` | user, type (NR-33, NR-34, NR-35, NR-10, ANAC/RPAS), issue and expiry |
| `modelo_pt` | approved template per work type, with checklist and field definitions |
| `permissao_trabalho` | the permit itself: number, work type, unit, area, equipment, description, validity window, state, version, requester, crew, hazards, controls |
| `pt_versao` | full snapshot plus field-by-field diff, author and reason |
| `anexo` | APR, ASO, certificate, report, photo, sketch — with expiry and hash |
| `assinatura` | permit, user, approval role, timestamp, hash of the signed document |
| `audit_event` | append-only: actor, role, event type, source and target state, reason, timestamp, device, IP, geolocation, document hash, previous hash, event hash |
| `alerta` | type, target entity, deadline, escalation level, status |

## Profiles (`perfil`)

`requisitante`, `executante`, `tecnico_seguranca`, `area_responsavel`, `coordenador`,
`oim`, `auditor`, `admin`.

## Permit states

```
RASCUNHO → VALIDACAO → ANALISE_SMS → APROVACAO → LIBERACAO → EM_EXECUCAO → ENCERRADA → ARQUIVADA
```

Deviations: `SUSPENSA` (only from `EM_EXECUCAO`) and `REJEITADA` (returns to `RASCUNHO`).
No transition may be skipped.

## Integrity rules

- `audit_event` accepts inserts only. A correction is a new compensating event that
  references the original one.
- `hash_evento = H(hash_anterior + payload)`, forming a chain per permit.
- Foreign keys are enforced on SQLite through `PRAGMA foreign_keys=ON`, set on every
  connection in `app/database.py`.
