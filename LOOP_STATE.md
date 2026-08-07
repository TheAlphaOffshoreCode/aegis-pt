# LOOP_STATE — AEGIS PT

Fonte de verdade para retomar o trabalho. Atualizado ao fim de cada loop.

| Loop | Nome | Estado | Data |
|---|---|---|---|
| L0 | Bootstrap | ✅ concluído | 2026-08-05 |
| L1 | Modelo de dados e migrations | ✅ concluído | 2026-08-07 |
| L2 | Autenticação e RBAC | ✅ concluído | 2026-08-07 |
| L3 | CRUD de PT e formulário dinâmico | ✅ concluído | 2026-08-07 |
| L4 | Motor de regras determinístico | ✅ concluído | 2026-08-07 |
| L5 | Máquina de estados e fluxo de aprovação | ✅ concluído | 2026-08-07 |
| L6 | Trilha de auditoria imutável | ⏳ aguardando autorização | — |
| L7 | Anexos, validade e OCR | — | — |
| L8 | Busca estruturada e dossiê | — | — |
| L9 | IA: busca em linguagem natural | — | — |
| L10 | IA: geração de rascunho | — | — |
| L11 | Indicadores e alertas | — | — |
| L12 | PWA e operação offline | — | — |
| L13 | Auditoria de segurança e fechamento | — | — |

---

## L0 — Bootstrap (2026-08-05)

**Local:** `C:\Users\ALPHA MODE\Documents\1 - William\Projetos\TheAlphaOffshoreCode\aegis-pt`
**Remoto:** https://github.com/TheAlphaOffshoreCode/aegis-pt (público, CI verde)

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

---

## L1 — Modelo de dados e migrations (2026-08-07)

**Entregue:** 13 tabelas, uma revisão Alembic, schemas Pydantic e seed idempotente.
**Aceite:** `alembic upgrade head` cria o esquema, o seed roda duas vezes sem duplicar e
20 testes passam. A migration é comparada com o metadata dentro do próprio teste.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/models/tipos.py` | `agora_utc`, `TimestampMixin`, `enum_col` |
| `app/models/enums.py` | vocabulário do domínio (8 enums) |
| `app/models/organizacao.py` | `Unidade`, `Area`, `Equipamento` |
| `app/models/pessoa.py` | `Usuario`, `Certificacao` |
| `app/models/permissao.py` | `ModeloPT`, `PermissaoTrabalho`, `PTEquipe`, `PTVersao`, `Anexo`, `Assinatura` |
| `app/models/auditoria.py` | `AuditEvent`, `Alerta` |
| `app/models/__init__.py` | registro dos 13 modelos no metadata |
| `app/schemas/` | `base`, `organizacao`, `pessoa`, `permissao`, `auditoria` — 22 schemas |
| `app/seed.py` | seed idempotente, `python -m app.seed` |
| `app/database.py` | `NAMING_CONVENTION` no `Base.metadata` |
| `migrations/versions/53e061bd6036_*.py` | revisão inicial |
| `tests/conftest.py` | fixture `db` (tabelas nascem e morrem por teste) |
| `tests/test_modelo_dados.py`, `tests/test_schemas.py`, `tests/test_migration.py` | 15 testes novos |
| `requirements.txt` | `pydantic[email]` para validar e-mail em fronteira |

### Decisões

- **PK inteira, mais um `uuid` só na `permissao_trabalho`.** O L12 cria PT offline e
  autoincrement gerado em dois tablets colide na sincronização. Renumerar PT que já circulou
  não é opção; a coluna custa nada agora.
- **`enum_col()` com `values_callable`.** Sem isso o banco guarda `NR_35` e passa a divergir
  da norma, da API e da tela.
- **`NAMING_CONVENTION` no metadata.** Constraint anônima não sobrevive à recriação em batch
  do SQLite. Era agora ou renomear tudo depois.
- **`tipo_evento` e `alerta.tipo` como texto.** Catálogo que cresce a cada loop não cabe em
  CHECK sem exigir migration por evento novo.
- **`audit_event.pt_id` com `RESTRICT`** e assinatura única por (pt, papel, versão).
- **Sem schema de escrita** para estado, número, uuid e versão da PT, nem para evento de
  auditoria. Cliente que posta o próprio estado posta `LIBERACAO`.

### Segurança

Nenhum endpoint novo, logo nenhuma superfície HTTP nova. Revisão fechou uma armadilha antes
de existir: `AnexoCreate.nome_arquivo` agora recusa `/`, `\` e `..`, porque o L7 vai usar
esse nome para gravar em disco. Coberto por teste parametrizado.

---

## L2 — Autenticação e RBAC (2026-08-07)

**Entregue:** login com Argon2id, sessão JWT, dependências de RBAC e escopo por unidade.
**Aceite:** 29 testes passando, `/auth/login` devolve token, `/auth/eu` responde 401 sem
credencial, e a migration nova sobe numa base que já tinha usuários.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/security/credenciais.py` | hash Argon2id, token JWT, gasto de tempo contra oráculo |
| `app/security/dependencias.py` | `usuario_atual`, `exigir_perfis`, `unidades_visiveis` |
| `app/routers/auth.py` | `POST /auth/login`, `GET /auth/eu` |
| `app/schemas/auth.py` | `LoginRequest`, `TokenResponse`, `SessaoRead` |
| `app/models/pessoa.py` | `usuario`: `senha_hash`, `ultimo_acesso`, `unidade_id` |
| `app/config.py` | `token_expiracao_minutos` (480 = um turno) |
| `app/seed.py` | senha de desenvolvimento e lotação; guarda de ambiente em `semear()` |
| `migrations/versions/13bcae197fe3_*.py` | colunas de credencial, com `server_default` |
| `tests/test_auth.py` | 9 testes |

### Decisões

- **Sem endpoint de refresh**, apesar de o L0 tê-lo planejado. Refresh é uma segunda
  credencial de vida longa para guardar, rotacionar e revogar; sessão de 8 h cobre o turno
  inteiro e elimina o problema que ele resolveria. Reavaliar se o turno deixar de caber.
- **Token não carrega perfil.** Perfil e lotação são lidos do banco a cada requisição, então
  revogar acesso vale na hora — e não quando o token vencer.
- **`admin` passa em tudo** em `exigir_perfis`, por decisão explícita.
- **Escopo falha fechado:** usuário sem lotação e sem perfil global enxerga conjunto vazio.
- **Lotação é uma unidade só** (`usuario.unidade_id`). Multi-unidade viraria tabela
  associativa; hoje seria especulação.

### Segurança

- Mesma resposta `401` para senha errada, matrícula inexistente e conta desativada — e um
  Argon2 descartável no caminho da matrícula inexistente, para o tempo também não responder.
- `jwt.decode` com `algorithms=["HS256"]` explícito. Há teste que forja `alg: none`, outro
  com chave errada e outro expirado.
- Desativar usuário corta o acesso antes do token vencer — coberto por teste.
- A guarda do seed foi movida de `main()` para `semear()`: quem importa a função também
  esbarra nela.

---

## L3 — CRUD de PT e formulário dinâmico (2026-08-07)

**Entregue:** ciclo de rascunho da PT, formulário dinâmico validado por regra determinística,
escopo aplicado na consulta e o padrão de conflito `409` com pendência estruturada.
**Aceite:** 49 testes passando; PT criada ponta a ponta contra o banco de desenvolvimento
(`PT-2026-0001`, `RASCUNHO`), e formulário incompleto devolve 409 apontando cada campo.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/rules/pendencias.py` | `Pendencia`, `Severidade`, `ConflitoDeNegocio` |
| `app/rules/formulario.py` | validação das respostas contra a definição do modelo |
| `app/services/permissoes.py` | criar, listar, obter, atualizar; numeração; escopo na query |
| `app/routers/pts.py` | `/pts`, `/pts/{id}`, `/pts/modelos/{tipo_trabalho}` |
| `app/schemas/permissao.py` | `_PermissaoTrabalhoEntrada`, `Create`, `Update` |
| `app/main.py` | handler único de `ConflitoDeNegocio` → 409 |
| `app/seed.py` | 2 modelos de PT com campos e checklist; reparo de lotação |
| `tests/conftest.py` | fixtures `criar_usuario` e `autenticar`, reusadas por todos os testes |
| `tests/test_pts.py`, `tests/test_formulario.py` | 16 testes novos |

### Decisões

- **P10 resolvida por uso:** a coluna `respostas` era a antecipação certa — é onde o
  formulário dinâmico grava. Deixa de ser especulação e vira campo com consumidor.
- **Versão da PT não é criada a cada edição de rascunho.** `pt_versao` guarda o retrato de
  quando o documento circulou; versionar cada tecla no rascunho seria ruído. Nasce no L5.
- **Sem `DELETE` de PT.** A trilha usa `RESTRICT` e o documento é registro legal; o que
  existe é arquivar, no L5.
- **Numeração pelo ano de emissão**, não da janela de validade: PT aberta em dezembro para
  trabalho em janeiro pertence à numeração de dezembro.
- **`nao_e_o_requisitante` responde 409, não 403.** É posse do rascunho, não perfil, e o
  formato de conflito do projeto é a lista de pendências. A PT já está no escopo de quem pediu.
- **Sem paginação na listagem** enquanto o volume é de uma unidade. Entra no L8, junto com a
  busca estruturada.

### Segurança

- Escopo entra na consulta (`aplicar_escopo`), nunca peneira o resultado. Fora do escopo é
  **404**, porque 403 já confirmaria que a PT existe.
- `numero`, `uuid`, `estado`, `versao` e `requisitante_id` vêm do servidor; teste manda os
  quatro no corpo e confirma que são ignorados.
- Chaves estrangeiras vindas do payload (equipe, área, equipamento, modelo) são validadas no
  serviço: `IntegrityError` no commit seria um 500 onde cabia uma pendência nomeando o campo.
- Colisão de número tem retry com a UNIQUE como árbitro, em vez de 500 no meio da emissão.

---

## L4 — Motor de regras determinístico (2026-08-07)

**Entregue:** as regras de risco da PT, puras e testáveis isoladamente, com `GET
/pts/{id}/pendencias` expondo o veredito sem decidir nada.
**Aceite:** 72 testes passando (19 do motor rodam em 0,06 s, por não tocarem no banco); a PT do
banco de desenvolvimento é reprovada com três bloqueios corretos e um responsável em cada.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/rules/exigencias.py` | as tabelas: certificação, anexos, duração máxima, incompatibilidades |
| `app/rules/motor.py` | janela, certificações, documentos, simultaneidade, segregação de funções |
| `app/rules/pendencias.py` | `bloqueio()` e `aviso()` consolidados, antes duplicados em três lugares |
| `app/services/permissoes.py` | `concorrentes_na_area`, `pendencias_da_pt` |
| `app/routers/pts.py` | `GET /pts/{id}/pendencias` |
| `app/models/tipos.py` | **`UTCDateTime`** — normaliza fuso na borda do banco |
| `tests/test_motor.py` | 19 testes puros |

### Decisões

- **`exigencias.py` é dado, não lógica.** Mudar uma exigência normativa não deveria significar
  editar fluxo de controle — e é o arquivo que alguém de segurança consegue revisar.
- **Regra pura, sem banco.** Quem consulta é o serviço; a regra recebe e devolve. É o que
  permite testar cada limite sozinho em vez de montar meio sistema por caso.
- **Certificação é conferida contra o fim da janela, não contra hoje.** Certificado que vence
  no meio do serviço deixa o trabalhador sem habilitação exatamente enquanto está exposto.
- **Ausência na tabela significa "nada a exigir"**, e está escrito lá — içamento não tem
  habilitação individual entre as cinco normas cadastradas.
- **`admin` não assina** em papel técnico: administra o sistema, não responde pelo documento.
- O endpoint responde **200 com `liberavel: false`**. É consulta; quem impede a transição é o L5.

### Defeito encontrado e corrigido: fuso na borda do banco

`pt.valida_ate <= agora` levantou `TypeError` no primeiro teste de integração. Causa: o SQLite
**não armazena offset**, então `DateTime(timezone=True)` devolve datetime *naive* dele e *aware*
do PostgreSQL. O mesmo código passaria em produção e quebraria em desenvolvimento.

Corrigido na raiz com o `TypeDecorator` `UTCDateTime`, aplicado a todas as colunas de data, em
vez de converter dentro do motor — remendo no motor deixaria o próximo comparador repetindo o
bug. O teste de migration confirmou que o tipo não altera o esquema, e há teste novo provando
que a data volta do banco com fuso.

---

## L5 — Máquina de estados e fluxo de aprovação (2026-08-07)

**Entregue:** o fluxo completo da PT, com assinatura por etapa, versionamento e escrita da
trilha encadeada.
**Aceite:** 90 testes passando. No banco de desenvolvimento, uma PT percorreu
`RASCUNHO → VALIDACAO → ANALISE_SMS → APROVACAO → LIBERACAO` com quatro assinaturas e quatro
elos de trilha, e **parou na liberação** por causa da NR-35 vencida que o seed plantou no L1.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/workflow/maquina.py` | o grafo de transições, papel e exigência de risco por passo |
| `app/audit/documento.py` | `snapshot_da_pt`, `hash_do_documento`, `diferencas` |
| `app/audit/trilha.py` | escrita append-only encadeada (`H(anterior + payload)`) |
| `app/services/transicoes.py` | orquestra: valida, assina, versiona, registra |
| `app/routers/pts.py` | `GET`/`POST /pts/{id}/transicoes` |
| `app/models/permissao.py` | `Assinatura.estado_destino` e nova unicidade |
| `migrations/versions/126544508b16_*.py` | coluna e constraint, em duas etapas |
| `tests/test_workflow.py`, `tests/test_transicoes.py` | 18 testes novos |

### Decisões

- **O hash do documento exclui o `estado`.** Assinar é assinar conteúdo, não posição no fluxo.
  Se o hash mudasse a cada transição, duas assinaturas da mesma versão não bateriam e nada
  seria conferível depois. Provado no smoke: as quatro assinaturas compartilham um só hash.
- **A cadeia de auditoria nasce aqui, não no L6.** A regra 6 exige o registro no instante da
  transição; gravar agora e encadear depois seria auditar um passado não guardado. Ao L6 ficam
  o verificador, a API de trilha e o evento compensatório.
- **Regra 6 sai de graça do grafo.** Pular etapa não é caso a recusar: o passo não existe.
- **`motivo` é obrigatório para rejeitar e suspender.** Sem ele não há o que corrigir, e é o
  primeiro registro que uma investigação procura.
- **Suspender e retomar não assinam.** São eventos operacionais que se repetem na mesma versão;
  ficam na trilha, com o mesmo ator, momento, contexto e hash.

### Defeito de modelagem do L1, corrigido aqui

A unicidade da assinatura era `(pt, papel, versão)`. O fluxo real mostrou que **o mesmo papel
assina etapas diferentes de propósito** — o executante inicia e encerra o trabalho, o técnico
analisa e depois suspende. A constraint passou a ser `(pt, etapa, versão)`, com a coluna
`estado_destino` nova.

A migration **não** leva `server_default`: não existe etapa plausível para inventar num
documento já assinado, e chutar uma seria falsificar registro. A coluna entra nula e vira
`NOT NULL` no passo seguinte — se houver assinatura anterior ao fluxo, falha alto. Nenhuma pode
existir, porque até o L5 não havia como assinar.

### Pendências abertas

| # | Pendência | Loop de destino |
|---|---|---|
| P1 | Fontes Oswald e JetBrains Mono servidas localmente (hoje só fallback de sistema) | L11/L12 |
| P2 | `manifest.json` e service worker | L12 |
| P3 | Cabeçalhos de segurança, rate limiting, tratamento de erro sem stack | L13 |
| ~~P4~~ | ~~Dependências de auth~~ — `argon2-cffi` e `pyjwt` no `requirements.txt` | resolvido no L2 |
| P5 | Dependências de IA (SDK Anthropic, índice vetorial) entram no `requirements.txt` | L9 |
| P6 | `starlette.testclient` avisa que `httpx` está depreciado em favor de `httpx2` — sem efeito hoje | reavaliar em L13 |
| ~~P7~~ | ~~Repositório sem remote~~ — publicado em TheAlphaOffshoreCode/aegis-pt, CI verde | resolvido em 05/08/2026 |
| ~~P8~~ | ~~`security-review` sem linha de base~~ — destravada pelo commit inicial | resolvido em 05/08/2026 |
| P9 | Skill `impeccable` aplicada às telas reais; o shell atual é diagnóstico | L11/L12 |
| ~~P10~~ | ~~Coluna `respostas` especulativa~~ — virou o campo onde o formulário dinâmico grava | resolvido no L3 |
| P11 | `AuditEventRead`, `AlertaRead` e `AnexoCreate` existem sem consumidor até os loops que os usam | L6/L7/L11 |
| ~~P12~~ | ~~`usuario` sem credencial~~ — `senha_hash`, `ultimo_acesso` e `unidade_id` criados | resolvido no L2 |
| P13 | Compatibilidade com Python 3.11 só é provada no CI — esta máquina tem apenas 3.14 | contínuo |
| P14 | Login sem limite de tentativas e sem bloqueio de conta; sem lista de revogação de token — token vazado vale até vencer | L13 |
| P15 | Lotação é uma unidade só (`usuario.unidade_id`). Multi-unidade exigiria tabela associativa | quando aparecer o caso |
| P16 | Evento de auditoria de login e de criação de PT não é gravado: a cadeia de hash só nasce no L6 | L6 |
| P17 | `GET /pts` não pagina. Enquanto o escopo é uma unidade, cabe; entra com a busca estruturada | L8 |
| ~~P18~~ | ~~Nenhuma regra de risco~~ — motor determinístico entregue e exposto em `/pts/{id}/pendencias` | resolvido no L4 |
| ~~P19~~ | ~~Veredito do motor não impede nada~~ — entrada em `EM_EXECUCAO` exige risco limpo | resolvido no L5 |
| P23 | Retomada de PT suspensa não gera assinatura, só evento de trilha. Se a operação exigir assinatura formal, é índice parcial ou tabela de eventos assinados | quando pedirem |
| P24 | Não há verificador da cadeia de hash nem API de consulta da trilha; o evento compensatório também não existe | L6 |
| P25 | `PTVersao` é gravada mas não exposta: falta endpoint de histórico e diff | L8 |
| P20 | `documentos_obrigatorios` sempre acusa ausência enquanto o upload não existe. Correto, mas só deixa de ser ruído com o L7 | L7 |
| P21 | Duração máxima e pares incompatíveis são constantes em `exigencias.py`. Se a operação quiser ajustar sem deploy, viram configuração | quando pedirem |
| P22 | API aceita datetime sem fuso e o trata como UTC. Exigir offset explícito é decisão do contrato HTTP | L12/L13 |

### Ponto exato de retomada

L1 fechado e verificado: 20 testes passando, `alembic upgrade head` e `downgrade base` executam,
o seed roda duas vezes sem duplicar, `/health` continua 200. O clone do PC A precisou de `.venv`
e `.env` próprios — nenhum dos dois vem do repositório.

L5 fechado e verificado: 90 testes passando; no banco de desenvolvimento a `PT-2026-0002`
percorreu o fluxo até `LIBERACAO` com quatro assinaturas de mesmo hash e quatro elos de trilha
encadeados, e foi barrada na entrada em execução pela NR-35 vencida.

Próximo passo: **L6 — Trilha de auditoria imutável**. Metade já existe: `app/audit/trilha.py`
escreve a cadeia `H(anterior + payload)` a cada transição, e só faz INSERT. Falta:

- **Verificador de integridade** — percorrer a cadeia de uma PT e apontar onde ela quebra. É o
  teste obrigatório "audit chain detects tampering", que ainda não existe.
- **API de consulta** (`/pts/{id}/trilha`), com o escopo da regra 5 aplicado na consulta.
- **Evento compensatório**: `evento_compensado_id` está no modelo e nunca foi usado. Correção
  é evento novo apontando para o original, jamais `UPDATE`.
- Cobrir também os eventos que ainda não são registrados: login (P16) e criação de PT.

Cuidado: hoje só transições geram evento. Se o L6 passar a registrar criação e edição, a
cadeia de PTs antigas continua válida — ela é por PT e por ordem de inserção, não global.

Lembretes que já custaram caro: todo modelo novo entra em `app/models/__init__.py`, senão o
autogenerate o ignora; toda coluna de enum passa por `enum_col()`; nenhuma constraint nasce sem
nome, por causa do batch mode do SQLite; e coluna `NOT NULL` nova precisa de `server_default`
na migration quando a tabela já tem linhas.

Credenciais de desenvolvimento: matrículas `10001` a `10005`, senha `aegis-dev-2026`
(`python -m app.seed`, que recusa rodar fora de `environment=development`).
