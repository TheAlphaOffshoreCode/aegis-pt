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
| L3 | `/pts` CRUD, dynamic form schema per work type |
| L5 | `/pts/{id}/transicoes`, `/pts/{id}/assinaturas` |
| L6 | `/pts/{id}/trilha`, chain integrity verification |
| L7 | `/pts/{id}/anexos` |
| L8 | `/pts` structured search, `/pts/{id}/dossie` |
| L9 | `/ai/consulta` (read-only tools) |
| L10 | `/ai/rascunho` |
| L11 | `/indicadores/*`, `/alertas` |
