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

## Planned

| Loop | Endpoints |
|---|---|
| L2 | `POST /auth/login`, `POST /auth/refresh` |
| L3 | `/pts` CRUD, dynamic form schema per work type |
| L5 | `/pts/{id}/transicoes`, `/pts/{id}/assinaturas` |
| L6 | `/pts/{id}/trilha`, chain integrity verification |
| L7 | `/pts/{id}/anexos` |
| L8 | `/pts` structured search, `/pts/{id}/dossie` |
| L9 | `/ai/consulta` (read-only tools) |
| L10 | `/ai/rascunho` |
| L11 | `/indicadores/*`, `/alertas` |
