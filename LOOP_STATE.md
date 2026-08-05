# LOOP_STATE — AEGIS PT

Fonte de verdade para retomar o trabalho. Atualizado ao fim de cada loop.

| Loop | Nome | Estado | Data |
|---|---|---|---|
| L0 | Bootstrap | ✅ concluído | 2026-08-05 |
| L1 | Modelo de dados e migrations | ⏳ aguardando autorização | — |
| L2 | Autenticação e RBAC | — | — |
| L3 | CRUD de PT e formulário dinâmico | — | — |
| L4 | Motor de regras determinístico | — | — |
| L5 | Máquina de estados e fluxo de aprovação | — | — |
| L6 | Trilha de auditoria imutável | — | — |
| L7 | Anexos, validade e OCR | — | — |
| L8 | Busca estruturada e dossiê | — | — |
| L9 | IA: busca em linguagem natural | — | — |
| L10 | IA: geração de rascunho | — | — |
| L11 | Indicadores e alertas | — | — |
| L12 | PWA e operação offline | — | — |
| L13 | Auditoria de segurança e fechamento | — | — |

---

## L0 — Bootstrap (2026-08-05)

**Local:** `C:\Users\ALPHA MODE\Documents\Projetos\TheAlphaOffshoreCode\aegis-pt`

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `requirements.txt` | dependências do L0 |
| `.env.example`, `.gitignore` | configuração e proteção de segredo |
| `app/config.py` | `Settings` (Pydantic), prefixo `AEGIS_`, `secret_key` obrigatório |
| `app/database.py` | engine, `SessionLocal`, `Base`, `get_db`, `PRAGMA foreign_keys=ON` |
| `app/main.py` | app FastAPI, CORS, `/`, mount `/static` |
| `app/routers/health.py` | `GET /health` com `SELECT 1` |
| `app/models/__init__.py` | registro de modelos para o metadata do Alembic |
| `alembic.ini`, `migrations/env.py` | Alembic lendo a URL do settings, `render_as_batch` no SQLite |
| `static/index.html`, `static/css/aegis.css`, `static/js/app.js` | shell do PWA com a identidade visual |
| `tests/conftest.py`, `tests/test_bootstrap.py` | 5 testes |
| `CLAUDE.md` | contrato de loops, regras invioláveis, armadilhas já pagas |
| `README.md`, `docs/API.md`, `docs/DATA_MODEL.md`, `docs/SECURITY.md` | documentação |

### Correções aplicadas na revisão de fechamento

- O listener do `PRAGMA foreign_keys=ON` estava registrado na **classe** `Engine`, o que o
  aplicaria a qualquer engine criada no processo. Passou a ser registrado na instância.
- Novo teste `test_foreign_keys_ativas_no_sqlite` — a garantia agora é provada, não só afirmada.
- `alembic revision --autogenerate` verificado de ponta a ponta (revisão gerada e removida);
  `upgrade head` sozinho não exercita `target_metadata` nem `render_as_batch`.

### Versões resolvidas (Python 3.14.6)

`fastapi 0.141.1` · `uvicorn 0.52.1` · `pydantic 2.13.4` · `pydantic-settings 2.14.2`
`SQLAlchemy 2.0.51` · `alembic 1.19.0` · `pytest 9.1.1` · `httpx 0.28.1`

### Pendências abertas

| # | Pendência | Loop de destino |
|---|---|---|
| P1 | Fontes Oswald e JetBrains Mono servidas localmente (hoje só fallback de sistema) | L11/L12 |
| P2 | `manifest.json` e service worker | L12 |
| P3 | Cabeçalhos de segurança, rate limiting, tratamento de erro sem stack | L13 |
| P4 | Dependências de auth (JWT, Argon2/bcrypt) entram no `requirements.txt` | L2 |
| P5 | Dependências de IA (SDK Anthropic, índice vetorial) entram no `requirements.txt` | L9 |
| P6 | `starlette.testclient` avisa que `httpx` está depreciado em favor de `httpx2` — sem efeito hoje | reavaliar em L13 |
| P7 | Repositório git local sem remote; publicação no GitHub não foi solicitada | quando o autor decidir |
| P8 | Skill `security-review` exige diff contra `origin/HEAD`; sem commit inicial não roda | destrava no 1º commit |
| P9 | Skill `impeccable` aplicada às telas reais; o shell atual é diagnóstico | L11/L12 |

### Ponto exato de retomada

L0 fechado e verificado (`/health` 200, `/docs` 200, 4 testes passando, `alembic upgrade head`
executa). Próximo passo: **L1 — Modelo de dados e migrations**, criando os modelos da seção 5
do prompt em `app/models/`, os schemas em `app/schemas/`, a primeira revisão Alembic e o seed
(1 unidade, 3 áreas, 5 usuários, 2 equipamentos, certificações com uma vencida de propósito).
Todo modelo novo precisa ser importado em `app/models/__init__.py`, senão não entra no metadata
e o autogenerate do Alembic o ignora.
