# API

Base URL in development: `http://127.0.0.1:8000`.
The interactive contract is always current at `/docs`; this file records intent and rules
that OpenAPI cannot express.

## Conventions

- Domain names are Portuguese (`permissao_trabalho`, `assinatura`); technical structures
  are English (`router`, `service`, `repository`).
- Timestamps are ISO 8601 with timezone.
- Errors return `{"detail": ...}`. Business conflicts (blocking pendency, invalid state
  transition) return `409` with the structured pendency list, never a bare message.

## Endpoints

### `GET /health`

No authentication. Confirms the process is alive and the database answers `SELECT 1`.

```json
{ "status": "ok", "app": "AEGIS PT", "environment": "development", "database": "ok" }
```

A failing database raises, producing a `500` — an unhealthy service must never report `200`.

### `GET /`

Serves the PWA shell (`static/index.html`). Excluded from the OpenAPI schema.

### `GET /static/{path}`

Static assets. No user data is ever served from here.

### `POST /auth/login`

No authentication. Takes `{"matricula": ..., "senha": ...}` and returns a bearer token.

```json
{ "access_token": "eyJ...", "token_type": "bearer", "expira_em_minutos": 480 }
```

Wrong password, unknown matrícula and deactivated account all return the same `401` with the
same message. Telling them apart would answer "does this person exist here?" to anyone who
asks. The unknown-matrícula path still runs a throwaway Argon2 verification, so response time
does not answer it either.

### `GET /auth/eu`

Requires `Authorization: Bearer <token>`. Returns who is authenticated and what they reach:

```json
{ "id": 1, "matricula": "10001", "nome": "...", "perfil": "requisitante",
  "unidade_id": 1, "unidades": [1] }
```

`unidades: null` means global reach (`auditor`, `admin`). An empty list means the account has
no posting and therefore sees nothing — the scope fails closed.

### `GET /pts/modelos/{tipo_trabalho}`

The active form definition for a work type — what the PWA renders the screen from. Each field
carries `chave`, `rotulo`, `tipo` (`texto`, `numero`, `data`, `booleano`, `selecao`),
`obrigatorio` and, for `selecao`, its `opcoes`.

Registered **before** `/pts/{pt_id}`: Starlette matches in registration order, so the reverse
order would make this route unreachable.

### `POST /pts`

Opens a permit in `RASCUNHO`. Restricted to `requisitante`, `area_responsavel` and
`coordenador` (plus `admin`).

`numero`, `uuid`, `estado`, `versao` and `requisitante_id` are assigned by the server and
ignored if sent. The number is `PT-AAAA-NNNN`, sequential within the year of **issue** — a
permit opened in December for January work belongs to December's numbering.

### `GET /pts` — structured search

Filters combine with `AND`: `numero`, `texto` (matches the description, case-insensitive),
`estado`, `tipo_trabalho`, `unidade_id`, `area_id`, `equipamento_id`, `requisitante_id`,
`vigentes_em`, `inicio_apos`, `inicio_antes`. Paging via `limite` (1–200, default 50) and
`deslocamento`.

```json
{ "total": 137, "limite": 50, "deslocamento": 0, "itens": [ ... ] }
```

`total` is the count **before** the page cut — the screen needs it to know how many pages
exist. It goes through the same scope and the same filters as the listing: counting over a
wider universe than the one displayed would already tell the caller how many permits exist
beyond their reach.

Passing `unidade_id` for a unit outside your scope returns empty, not that unit. Scope is not
a filter anyone chooses; it is a restriction always applied.

### `GET /pts/{id}` · `PATCH /pts/{id}`

A permit outside the caller's scope answers `404`, not `403` — "you may not see this one"
already confirms it exists. `PATCH` only edits a permit still in `RASCUNHO`, and only by its
requester; anything else is a state transition, which is L5.

### `GET /pts/{id}/versoes` · `GET /pts/{id}/dossie`

`versoes` returns the history: each revision's snapshot plus a field-by-field `diff` against
the previous one, the author and the reason.

`dossie` is the whole permit in one document — data, versions, signatures, attachments, crew,
audit trail, **whether that trail still verifies**, and the rule engine's current verdict. The
integrity flag travels with it on purpose: a history that does not say whether it was tampered
with is not evidence, and evidence is exactly what a dossier is requested as.

### `GET /pts/{id}/pendencias`

The rule engine's verdict on a permit. **A query, not a decision** — it answers `200` even when
the permit is unreleasable, because seeing what is missing is how the requester fixes it.

```json
{ "pt_id": 12, "numero": "PT-2026-0012", "liberavel": false,
  "pendencias": [ { "codigo": "certificacao_vencida", "severidade": "bloqueante",
                    "mensagem": "NR-35 de Rafael Souza vence em 23/06/2026, antes do fim da janela da PT",
                    "campo": "equipe", "responsavel": "requisitante" } ] }
```

`liberavel` is false whenever any pendency is `bloqueante`; `atencao` informs without blocking.
Enforcement of this verdict at the transition is L5 — this endpoint never changes state.

### `GET /pts/{id}/transicoes` · `POST /pts/{id}/transicoes`

The listing returns the steps available from the current state and whether **this** user may
take each one — so the screen does not reimplement the state machine, and an authorization rule
does not end up duplicated in a browser where it can drift.

```json
[ { "destino": "ANALISE_SMS", "papel": "area_responsavel", "assina": true, "permitida": false } ]
```

`POST` takes `{"destino": ..., "motivo": ..., "geolocalizacao": ...}` and returns the permit.
`motivo` is required for `REJEITADA` and `SUSPENSA` — rejecting without saying why leaves
nothing to correct, and it is the first record an incident investigation looks for.

Device and IP come from the request itself, never from the body. Every transition writes an
`audit_event` carrying actor, timestamp, context and document hash (rule 6).

## The approval flow

```text
RASCUNHO → VALIDACAO → ANALISE_SMS → APROVACAO → LIBERACAO → EM_EXECUCAO → ENCERRADA → ARQUIVADA
```

| Step | Signs as | Notes |
|---|---|---|
| → `VALIDACAO` | `requisitante` | freezes a `pt_versao` snapshot |
| → `ANALISE_SMS` | `area_responsavel` | |
| → `APROVACAO` | `tecnico_seguranca` | |
| → `LIBERACAO` | `coordenador` | |
| → `EM_EXECUCAO` | `executante` | **requires the rule engine clean** |
| → `ENCERRADA` | `executante` | |
| → `ARQUIVADA` | `coordenador` | administrative, no signature |
| → `REJEITADA` | role of the current step | `motivo` required; returns to `RASCUNHO` |
| → `SUSPENSA` | `tecnico_seguranca` | only from `EM_EXECUCAO`, `motivo` required |

Skipping a step is not a special case to reject — the step simply does not exist in the graph,
so it fails like any undeclared transition would.

**The document hash excludes `estado`.** A signature signs content, not position in the flow; if
the hash changed on every transition, two signatures of the same version would differ and
nothing could be checked afterwards. All signatures of one version share one hash.

Signatures are unique per `(permit, step, version)` rather than per role: the same role signs
different steps legitimately — the executant starts *and* closes the work. Suspending and
resuming produce no signature at all, because they repeat within a version; they live in the
trail, which carries the same actor, timestamp, context and hash.

### `GET /pts/{id}/trilha`

The permit's audit trail, already verified link by link.

```json
{ "pt_id": 12, "numero": "PT-2026-0012", "integra": true, "quebras": [],
  "eventos": [ { "tipo_evento": "pt.criada", "ator_id": 3, "hash_anterior": null,
                 "hash_evento": "a4bca07a…", "versao_payload": 2, "…": "…" } ] }
```

`integra: false` comes with `quebras`, each naming the event, its position and whether the
content stopped matching its hash or the previous link no longer fits — which distinguishes an
**altered** event from a **removed** one.

### `POST /pts/{id}/trilha/{evento_id}/compensacao`

Corrects a record without touching it: appends a new event pointing at the original through
`evento_compensado_id`. Restricted to `coordenador` and `oim` (plus `admin`). The wrong event
stays visible — a trail that disappears when it is inconvenient is not a trail.

A compensation cannot be compensated: register a new event instead.

### `POST /pts/{id}/anexos` · `GET /pts/{id}/anexos` · `DELETE /pts/{id}/anexos/{anexo_id}`

Upload is `multipart/form-data`: `arquivo`, `tipo` and optional `valido_ate`.

The SHA-256 is computed **here**, over the bytes received — never accepted from the client. The
filename sent is kept as a label only; the path on disk is `{upload_dir}/{pt.uuid}/{uuid4}{ext}`,
and any directory component in the submitted name is stripped.

Extensions are an allowlist — `.pdf`, `.jpg`, `.jpeg`, `.png`. `.html` and `.svg` are excluded
deliberately: the browser would render them as a page. Size is capped by
`AEGIS_ANEXO_TAMANHO_MAXIMO_MB` (default 10), enforced during the read, and a partial file is
deleted rather than left behind.

Attaching is allowed in any state except `ARQUIVADA` — the APR arrives during analysis, the
report at closing. **Removing works only in `RASCUNHO`, and only for the requester:** once the
permit has circulated, the attachment is part of what people analysed.

### `GET /pts/{id}/anexos/{anexo_id}/conteudo`

Returns the file with the media type from the server's own map, `Content-Disposition:
attachment` and `X-Content-Type-Options: nosniff`. An attachment is third-party content and must
never be interpreted as a page inside the application's origin.

## Business conflicts

Every blocking pendency returns `409` with the structured list, produced by a single handler
so no route invents its own shape:

```json
{ "detail": [ { "codigo": "campo_obrigatorio", "severidade": "bloqueante",
                "mensagem": "'Vigia de fogo designado' é obrigatório e não foi preenchido",
                "campo": "vigia_de_fogo", "responsavel": null } ] }
```

Codes so far. Form and structure (L3): `campo_obrigatorio`, `tipo_invalido`, `opcao_invalida`,
`campo_desconhecido`, `modelo_invalido`, `modelo_incompativel`, `area_invalida`,
`equipamento_invalido`, `membro_invalido`, `fora_do_escopo`, `pt_nao_editavel`,
`nao_e_o_requisitante`, `numero_em_disputa`.

Risk (L4): `janela_vencida`, `janela_excede_o_maximo`, `janela_menor_que_a_duracao`,
`equipe_vazia`, `certificacao_ausente`, `certificacao_vencida`, `certificacao_a_vencer`,
`documento_ausente`, `documento_vencido`, `trabalhos_incompativeis`, `segregacao_de_funcoes`,
`papel_incompativel_com_o_perfil`, `assinante_inativo`.

Flow (L5): `transicao_invalida`, `motivo_obrigatorio`.

Trail (L6): `evento_inexistente`, `compensacao_de_compensacao`.

Attachments (L7): `extensao_nao_permitida`, `arquivo_vazio`, `arquivo_muito_grande`,
`pt_arquivada`, `anexo_nao_removivel`, `anexo_fora_da_area`.

`422` remains what it always was: the payload did not even parse. `409` means it parsed and
the business refused it.

## Authentication

Bearer JWT, `HS256`, signed with `AEGIS_SECRET_KEY`, valid for
`AEGIS_TOKEN_EXPIRACAO_MINUTOS` (default 480 — one offshore shift).

The token carries only `sub`, `iat` and `exp`. Profile and posting are read from the database
on every request, so revoking a profile or deactivating an account takes effect immediately
instead of lingering until the token expires.

**There is no refresh endpoint**, though L0 planned one. A refresh token is a second
long-lived credential to store, rotate and revoke; an 8-hour session covering a full shift
removes the need it was solving. Revisit if shifts stop fitting in one token.

## Planned

| Loop | Endpoints |
|---|---|
| L5 | `/pts/{id}/transicoes`, `/pts/{id}/assinaturas` |
| L6 | `/pts/{id}/trilha`, chain integrity verification |
| L7 | `/pts/{id}/anexos` |
| L8 | `/pts` structured search, `/pts/{id}/dossie` |
| L9 | `/ai/consulta` (read-only tools) |
| L10 | `/ai/rascunho` |
| L11 | `/indicadores/*`, `/alertas` |
