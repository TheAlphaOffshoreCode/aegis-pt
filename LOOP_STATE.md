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
| L6 | Trilha de auditoria imutável | ✅ concluído | 2026-08-07 |
| L7 | Anexos e validade (OCR adiado) | ✅ concluído | 2026-08-07 |
| L8 | Busca estruturada e dossiê | ✅ concluído | 2026-08-07 |
| L8.5 | Acervo legado e OCR | ⏳ proposto, adiado — o L9 veio antes | — |
| L9 | IA: busca em linguagem natural | ✅ concluído | 2026-08-07 |
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

---

## L6 — Trilha de auditoria imutável (2026-08-07)

**Entregue:** verificador de integridade, guarda de append-only no ORM, API de consulta da
trilha, evento compensatório e versionamento do formato do payload.
**Aceite:** 104 testes passando. No banco de desenvolvimento, a cadeia da `PT-2026-0002` fecha,
acusa exatamente um evento ao ser adulterada por SQL direto, e volta a fechar quando o valor é
restaurado — a guarda provada nos dois sentidos.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/audit/verificador.py` | recalcula elo a elo e aponta onde a cadeia não fecha |
| `app/audit/formato.py` | `VERSAO_PAYLOAD` — contrato congelado do que entra no hash |
| `app/audit/trilha.py` | `montar_payload` versionado, usado pela escrita e pela conferência |
| `app/models/auditoria.py` | `versao_payload` e o listener que recusa `UPDATE`/`DELETE` |
| `app/services/auditoria.py` | consulta, conferência e compensação |
| `app/routers/pts.py` | `GET /pts/{id}/trilha` e `POST .../compensacao` |
| `app/services/permissoes.py` | eventos de criação e edição da PT |
| `migrations/versions/66f40a59708d_*.py` | coluna `versao_payload` |
| `tests/test_auditoria.py` | 14 testes |

### Decisões

- **Append-only virou garantia executável.** Listener `before_flush` na `SessionLocal` —
  não na classe `Session`, que é a armadilha já paga no L0 com o `PRAGMA foreign_keys`.
- **Duas conferências por elo**, porque falham por motivos diferentes: `hash_anterior` errado
  denuncia evento removido ou reordenado; `hash_evento` errado denuncia evento alterado.
- **A trilha começa no nascimento da PT**, não na primeira transição.
- **Compensação não se compensa**: registre um evento novo.

### O defeito que só o smoke pegou

Ao acrescentar `evento_compensado_id` ao payload, **todos os eventos gravados no L5 passaram a
acusar adulteração** — o verificador recalculava por um formato que não era o da selagem. Os
testes não viram, porque criam tudo do zero com o código novo; só a base que atravessou dois
loops tinha o estado antigo.

Pelo critério escrito no próprio módulo — "um verificador que dá alarme falso é pior que
nenhum" — isso não podia ficar documentado como limitação. Cada evento passou a guardar a
`versao_payload` com que nasceu, e o formato virou contrato: acrescentar campo exige subir a
versão e manter o formato anterior montável. Coberto por dois testes.

---

## L7 — Anexos e validade (2026-08-07)

**Entregue:** upload com hash calculado no servidor, validade, download seguro, remoção
restrita e registro na trilha. **O OCR foi adiado de propósito** — ver abaixo.
**Aceite:** 118 testes passando. No banco de desenvolvimento, anexar APR e ASO **apagou a
pendência `documento_ausente`** que existia desde o L4, sobrando apenas a certificação vencida.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/services/anexos.py` | gravação, hash, allowlist, limite de tamanho, remoção |
| `app/routers/pts.py` | upload, listagem, download e remoção |
| `app/config.py` | `upload_dir` e `anexo_tamanho_maximo_mb` |
| `tests/conftest.py` | uploads dos testes isolados e limpos por teste |
| `tests/test_anexos.py` | 15 testes |
| `requirements.txt` | `python-multipart` |

### Por que o OCR não entrou

Não foi falta de tempo. O OCR exige um binário de sistema (Tesseract) no runner e no servidor,
e o valor dele — ingerir o acervo de PTs em papel — depende de um **fluxo de importação em
lote que não existe**: não há modelo, tela nem endpoint para "acervo legado". Implementá-lo
agora seria construir a peça que ninguém chama, e ainda pagar a dependência de sistema no CI.

Entra no L8, junto com a busca e o dossiê, que é onde o acervo importado passa a ter para onde
ir. Registrado como P28.

### Decisões

- **Extensão por allowlist**, com `.html` e `.svg` fora de propósito: o navegador os renderiza
  como página, e anexo é conteúdo de terceiro.
- **Anexar vale em qualquer estado menos `ARQUIVADA`** — a APR chega na análise, o relatório no
  encerramento. **Remover, só em `RASCUNHO` e só pelo requisitante:** depois que a PT circulou,
  o anexo faz parte do que as pessoas analisaram.
- **Anexos não entram no hash do documento.** O hash cobre o formulário que é assinado; o
  anexo tem o seu próprio, e as duas coisas vão para a trilha.
- **`AnexoCreate` foi apagado.** O upload usa `Form`/`UploadFile`, então o schema virou código
  morto — mas a garantia que ele carregava (nada de caminho no nome) mudou para o serviço, com
  teste junto.

### Segurança

- Caminho gerado por nós (`{upload_dir}/{pt.uuid}/{uuid4}{ext}`); qualquer diretório no nome
  enviado é descartado. `caminho_absoluto()` reconfere que o arquivo está sob `upload_dir`.
- Download sempre `attachment` + `nosniff`, com o tipo saindo do nosso mapa e não do que o
  cliente declarou. O `Content-Disposition` é gerado pelo Starlette — header montado à mão com
  nome vindo do cliente é injeção esperando acontecer.
- Limite de tamanho conferido **durante** a leitura, e arquivo parcial é apagado.

### O defeito que só o CI pegou

A primeira versão sanitizava o nome com `Path(nome).name`. **Passou em tudo no Windows e
quebrou no CI**, porque no Linux o `Path` não trata `\` como separador — então
`..\..\windows\system32\sam.pdf` chegava inteiro ao banco no servidor, e parecia limpo na
máquina de desenvolvimento.

Não era falha de teste: era a garantia anunciada valendo só no ambiente que não é o de
produção. Corrigido com `PureWindowsPath`, que reconhece os dois separadores em qualquer
sistema, e o teste passou a conferir o valor exato esperado em vez de só procurar caracteres.

Fica como regra: **quem manda o nome é um cliente qualquer, não o sistema de arquivos local.**

---

## L8 — Busca estruturada e dossiê (2026-08-07)

**Entregue:** busca com onze filtros combináveis e paginação, histórico de versões com diff, e
o dossiê completo da PT.
**Aceite:** 136 testes passando. No banco de desenvolvimento, o dossiê da `PT-2026-0002` traz
4 assinaturas com suas etapas, 2 anexos, 6 eventos com trilha íntegra e a pendência restante.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/services/permissoes.py` | `buscar_pts` com filtros e paginação; contagem no mesmo escopo |
| `app/services/dossie.py` | composição do dossiê e histórico de versões |
| `app/schemas/permissao.py` | `FiltroPT`, `PaginaDePTs`, `DossieRead` |
| `app/routers/pts.py` | busca paginada, `/versoes` e `/dossie` |
| `tests/test_busca.py` | 17 testes |

### Decisões

- **`GET /pts` mudou de contrato**: devolvia lista, agora devolve página
  (`total`, `limite`, `deslocamento`, `itens`). Quebra declarada, feita antes de existir
  cliente — o PWA do L12 já nasce com o formato certo.
- **A contagem passa pelo mesmo escopo e pelos mesmos filtros.** `total` global diria quantas
  PTs existem fora do alcance de quem perguntou, sem devolver nenhuma — vazamento que não
  retorna linha nenhuma continua sendo vazamento.
- **Filtro não é escape**: pedir `unidade_id` fora do escopo devolve vazio, não a unidade.
- **`texto` compara em minúsculas dos dois lados**, porque o SQLite só é insensível a
  maiúsculas em ASCII e a descrição é em português.
- **O dossiê carrega `trilha_integra`.** Histórico que não diz se foi adulterado não serve como
  prova, e é como prova que o dossiê é pedido.
- **P25 resolvida**: `PTVersao` era gravada desde o L5 e nunca exposta; agora tem endpoint
  próprio e entra no dossiê, com o diff campo a campo.

### O OCR continua fora, e vira loop próprio (L8.5)

Repetir a decisão sem revisitá-la seria desonesto, então revisitei: o que falta para o OCR não
é o OCR. É **modelo de documento legado, ingestão em lote, indexação e vínculo com a PT** —
um loop inteiro. Enfiá-lo aqui entregaria busca e acervo pela metade.

Proposto como **L8.5 — Acervo legado e OCR**, com escopo próprio, antes do L9 (a IA precisa do
acervo indexado para ter o que citar).

---

## L9 — IA: busca em linguagem natural (2026-08-07)

**Entregue:** `POST /ai/consulta`, três ferramentas somente-leitura e o laço de tool-calling
manual contra a Claude API, com as regras 1, 2, 3, 5 e 7 sustentadas por estrutura.
**Aceite:** 153 testes passando (17 novos), a suíte inteira sem rede nem chave. Com a aplicação
no ar sem chave, `/ai/consulta` responde 503 e `/pts` continua servindo normalmente.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/ai/ferramentas.py` | `buscar_pts`, `detalhar_pt`, `pendencias_da_pt` — escopo fechado no código |
| `app/ai/agente.py` | laço de tool-calling, coleta de fontes, substituição por "não encontrei" |
| `app/schemas/ai.py`, `app/routers/ai.py` | contrato HTTP e o 503 sem chave |
| `app/config.py` | `anthropic_api_key`, `ai_modelo`, `ai_max_tokens`, `ai_esforco`, `ai_max_iteracoes` |
| `tests/conftest.py` | chave vazia à força: a suíte não tem caminho para a rede |
| `tests/test_ia.py` | 17 testes |

### Decisões

- **Laço manual, não o tool runner do SDK.** Três motivos concretos: o escopo precisa entrar
  nas ferramentas antes da chamada, as fontes são colhidas a cada passo do que o banco
  devolveu, e assim a suíte roda com um cliente falso injetado. O runner faria o laço por nós
  escondendo justamente os dois pontos que aqui são a garantia — e ainda é beta.
- **A regra 3 virou código, não instrução.** `executar()` devolve as PTs que a consulta de fato
  alcançou; sem nenhuma, `_com_fontes` joga o texto do modelo fora e responde "não encontrei".
  Ler número de PT do texto com regex faria a regra depender do modelo, que é o que se evita.
- **Fora do escopo responde como inexistente**, igual ao resto da API desde o L3.
- **O conjunto de ferramentas tem teste próprio.** Ferramenta nova quebra a suíte de propósito:
  a regra 1 é revisada por gente antes de a quarta ferramenta existir.
- **`temperature`, `top_p` e `top_k` ficam de fora** — são `400` no Opus 5, onde o raciocínio é
  adaptativo e ligado por padrão e divide `max_tokens` com a resposta. O controle é
  `output_config: {"effort": "medium"}`, e há teste conferindo que os três não são enviados.
- **Sem chave, só a IA cai.** `anthropic_api_key` nasce `None` e as rotas de IA respondem 503;
  a aplicação sobe e opera sem elas. Chave lida só em `construir_cliente()`, no backend.
- **Fallback de modelo (beta) ficou fora, e por escolha declarada.** Num sistema onde a resposta
  é sobre segurança do trabalho, trocar em silêncio quem responde é decisão do William, não
  minha. Fica proposto, não implementado.
- **O acervo legado (L8.5) continua fora.** O L9 se sustenta sobre o acervo digital que já
  existe; quando o OCR entrar, vira mais uma ferramenta, sem retrabalho no laço.

### Pendências abertas

| # | Pendência | Loop de destino |
|---|---|---|
| P1 | Fontes Oswald e JetBrains Mono servidas localmente (hoje só fallback de sistema) | L11/L12 |
| P2 | `manifest.json` e service worker | L12 |
| P3 | Cabeçalhos de segurança, rate limiting, tratamento de erro sem stack | L13 |
| ~~P4~~ | ~~Dependências de auth~~ — `argon2-cffi` e `pyjwt` no `requirements.txt` | resolvido no L2 |
| ~~P5~~ | ~~Dependências de IA no `requirements.txt`~~ — `anthropic>=0.121`; índice vetorial não foi preciso, as ferramentas consultam o banco | resolvido no L9 |
| P6 | `starlette.testclient` avisa que `httpx` está depreciado em favor de `httpx2` — sem efeito hoje | reavaliar em L13 |
| ~~P7~~ | ~~Repositório sem remote~~ — publicado em TheAlphaOffshoreCode/aegis-pt, CI verde | resolvido em 05/08/2026 |
| ~~P8~~ | ~~`security-review` sem linha de base~~ — destravada pelo commit inicial | resolvido em 05/08/2026 |
| P9 | Skill `impeccable` aplicada às telas reais; o shell atual é diagnóstico | L11/L12 |
| ~~P10~~ | ~~Coluna `respostas` especulativa~~ — virou o campo onde o formulário dinâmico grava | resolvido no L3 |
| P11 | `AlertaRead` ainda sem consumidor. `AuditEventRead` passou a ser usado no L6; `AnexoCreate` foi apagado no L7 | L11 |
| ~~P12~~ | ~~`usuario` sem credencial~~ — `senha_hash`, `ultimo_acesso` e `unidade_id` criados | resolvido no L2 |
| P13 | Compatibilidade com Python 3.11 só é provada no CI — esta máquina tem apenas 3.14 | contínuo |
| P14 | Login sem limite de tentativas e sem bloqueio de conta; sem lista de revogação de token — token vazado vale até vencer | L13 |
| P15 | Lotação é uma unidade só (`usuario.unidade_id`). Multi-unidade exigiria tabela associativa | quando aparecer o caso |
| P16 | Criação e edição de PT já entram na trilha. Falta o evento de **login**, que não tem PT e por isso fica fora da cadeia por PT — decidir se ganha trilha própria | L13 |
| P26 | A cadeia é por PT. Não há cadeia global, então um evento sem PT (login) não tem onde encadear | L13 |
| P27 | O verificador percorre a cadeia inteira a cada consulta. Com trilha longa isso vira leitura completa por chamada | L11 |
| ~~P17~~ | ~~`GET /pts` sem paginação~~ — página com `total` no mesmo escopo | resolvido no L8 |
| P31 | Busca textual usa `LIKE %termo%`, que não usa índice. Com acervo grande, vira FTS (SQLite FTS5 / `tsvector` no Postgres) | L8.5 |
| ~~P18~~ | ~~Nenhuma regra de risco~~ — motor determinístico entregue e exposto em `/pts/{id}/pendencias` | resolvido no L4 |
| ~~P19~~ | ~~Veredito do motor não impede nada~~ — entrada em `EM_EXECUCAO` exige risco limpo | resolvido no L5 |
| P23 | Retomada de PT suspensa não gera assinatura, só evento de trilha. Se a operação exigir assinatura formal, é índice parcial ou tabela de eventos assinados | quando pedirem |
| ~~P24~~ | ~~Sem verificador, API de trilha e compensação~~ — os três entregues | resolvido no L6 |
| ~~P25~~ | ~~`PTVersao` gravada e não exposta~~ — `/pts/{id}/versoes` e dossiê, com diff | resolvido no L8 |
| ~~P20~~ | ~~`documento_ausente` sempre acusando~~ — upload entregue; a pendência some quando o papel chega | resolvido no L7 |
| P28 | **OCR do acervo legado.** Adiado por decisão: exige Tesseract como dependência de sistema e depende de um fluxo de importação em lote que ainda não existe | L8 |
| P29 | Anexo removido some do disco depois do commit. Se o `unlink` falhar, sobra arquivo órfão — inverter a ordem deixaria linha apontando para nada, que é pior | L13 |
| P30 | Só a extensão é validada, não o conteúdo real do arquivo. Conferir *magic bytes* barra um `.exe` renomeado para `.pdf` | L13 |
| P21 | Duração máxima e pares incompatíveis são constantes em `exigencias.py`. Se a operação quiser ajustar sem deploy, viram configuração | quando pedirem |
| P22 | API aceita datetime sem fuso e o trata como UTC. Exigir offset explícito é decisão do contrato HTTP | L12/L13 |
| P32 | **O caminho real contra a Claude API não foi exercitado**: esta máquina não tem chave. Provado o que dá — laço, escopo, fontes e 503 — com cliente falso e com a aplicação no ar. Falta uma consulta de verdade | assim que houver chave |
| P33 | Conteúdo de PT é texto de terceiro e chega ao modelo dentro do resultado da ferramenta. Não faz o modelo agir (não há com o quê), mas influencia a redação da resposta | L13, com a revisão de prompts |
| P34 | `/ai/consulta` sem limite de uso: cada consulta custa tokens e qualquer usuário autenticado repete à vontade. Limitado por consulta (6 iterações, 8000 tokens), não por pessoa | L13, junto com P14 |
| P35 | A consulta por IA não entra na trilha. Quem perguntou o quê pode ser registro que a auditoria vai querer — esbarra em P26 (evento sem PT não tem cadeia) | L13 |
| P36 | Fallback de modelo (beta) não implementado: numa recusa ou indisponibilidade, a consulta falha em vez de tentar outro modelo. Deliberado — trocar quem responde sobre segurança é decisão do William | quando o William decidir |

### Ponto exato de retomada

L1 fechado e verificado: 20 testes passando, `alembic upgrade head` e `downgrade base` executam,
o seed roda duas vezes sem duplicar, `/health` continua 200. O clone do PC A precisou de `.venv`
e `.env` próprios — nenhum dos dois vem do repositório.

L8 fechado e verificado: 136 testes passando; o dossiê da `PT-2026-0002` reúne 4 assinaturas,
2 anexos, 6 eventos com trilha íntegra e a pendência restante, e a busca filtra por texto,
tipo, estado e número respeitando o escopo na contagem.

L9 fechado e verificado: 153 testes passando, nenhum deles saindo para a rede. Com a aplicação
no ar e sem chave configurada, `/ai/consulta` responde 503 e `/pts` segue devolvendo as 2 PTs
do banco de desenvolvimento — a IA cai sozinha, sem levar o resto junto.

**Para usar de verdade:** pôr `AEGIS_ANTHROPIC_API_KEY` no `.env` (fora do repositório, o
`.gitignore` já cobre) e consultar:

```powershell
curl -X POST http://127.0.0.1:8000/ai/consulta -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{\"pergunta\":\"Quais PTs estao abertas?\"}'
```

Próximo passo: **decisão do William entre dois caminhos.**

**L10 — IA: geração de rascunho.** A continuação natural: a IA propõe um rascunho de PT a
partir de uma descrição, e o rascunho nasce como rascunho — sujeito ao motor de regras e ao
mesmo fluxo de assinatura de qualquer outro. A regra 1 continua valendo inteira: propor não é
aprovar. Reaproveita o laço, o escopo e a coleta de fontes do L9.

**L8.5 — Acervo legado e OCR** (ainda proposto). Escopo próprio: modelo `documento_legado`,
upload em lote, OCR com Tesseract, indexação do texto extraído e vínculo opcional com PT. Traz
a dependência de sistema para o CI (`apt-get install tesseract-ocr`). Depois do L9, entra como
mais uma ferramenta somente-leitura, sem mexer no laço. A busca textual atual (P31)
provavelmente vira FTS aqui.

Lembretes que já custaram caro: todo modelo novo entra em `app/models/__init__.py`, senão o
autogenerate o ignora; toda coluna de enum passa por `enum_col()`; nenhuma constraint nasce sem
nome, por causa do batch mode do SQLite; e coluna `NOT NULL` nova precisa de `server_default`
na migration quando a tabela já tem linhas.

Credenciais de desenvolvimento: matrículas `10001` a `10005`, senha `aegis-dev-2026`
(`python -m app.seed`, que recusa rodar fora de `environment=development`).
