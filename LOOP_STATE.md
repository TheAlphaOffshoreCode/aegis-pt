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
| L10 | IA: geração de rascunho | ✅ concluído | 2026-08-08 |
| L11 | Indicadores e alertas | ✅ concluído | 2026-08-08 |
| L12 | PWA e operação offline | ✅ concluído | 2026-08-08 |
| L13 | Auditoria de segurança e fechamento | ✅ concluído | 2026-08-08 |
| — | Verificação independente (P49, P50) | ✅ concluído | 2026-08-09 |
| — | Tela de emissão e anexos | ✅ concluído | 2026-08-09 |
| — | Trilha na tela e agendador de alertas (P41) | ✅ concluído | 2026-08-10 |
| — | Versão do service worker derivada do shell | ✅ concluído | 2026-08-10 |

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

---

## L10 — IA: geração de rascunho (2026-08-08)

**Entregue:** `POST /ai/rascunho` — a IA lê uma descrição em texto livre, consulta PTs
parecidas e propõe tipo de trabalho, descrição, perigos e controles; a PT nasce em `RASCUNHO`
pelo caminho normal de criação.
**Aceite:** 169 testes passando (16 novos), suíte inteira sem rede nem chave. Com a aplicação
no ar sem chave, `/ai/rascunho` responde 503 e `/pts` continua servindo.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/ai/rascunho.py` | schema da proposta, instruções e criação da PT |
| `app/ai/agente.py` | `conversar()` extraído: o laço do L9 virou compartilhado, não copiado |
| `app/schemas/ai.py`, `app/routers/ai.py` | `RascunhoRequest`/`RascunhoResponse` e `POST /ai/rascunho` |
| `app/services/permissoes.py` | `criar_pt` recebe `tipo_evento` (padrão inalterado) |
| `tests/test_ia_rascunho.py` | 16 testes |

### Onde a linha foi traçada, e por quê

A IA escreve **texto**: tipo de trabalho, descrição, perigos, controles. Ela não preenche
campo de formulário nenhum, e essa é a decisão central do loop. Os campos do modelo são
medição e atestado — `teste_de_gases_lie` sai de um detector calibrado, `altura_metros` de
uma trena, `area_isolada` de alguém que foi lá olhar. Um número plausível aqui é exatamente o
modo de falhar que a regra 2 existe para impedir.

O schema da proposta tem cinco campos e `additionalProperties: false`: **não existe forma de o
modelo devolver uma resposta de formulário**. Um teste fixa esse conjunto.

- **A medição entra pelo pedido e o modelo nunca a vê.** Um teste confere as duas metades: as
  respostas gravadas são as que o cliente mandou, e nenhum dos valores aparece no que foi
  enviado à API.
- **A PT nasce pelo mesmo `criar_pt` de sempre** — mesma validação, numeração, trilha e fluxo
  de assinatura pela frente. Propor não é aprovar (regra 1), e não há atalho.
- **A trilha marca `pt.criada_por_ia`.** Rodou no catálogo aberto de tipos de evento, não no
  payload: nenhum bump de `VERSAO_PAYLOAD`, nenhuma cadeia invalidada, e um rascunho proposto
  por IA fica identificável enquanto o documento existir.
- **A proposta é revalidada na chegada.** O schema prende a forma, não o significado: um
  `tipo_trabalho` fora do domínio volta como string válida. O Pydantic é o que transforma isso
  em recusa (502) em vez de PT quebrada.

### A colisão que valeu a pena parar para entender

O primeiro desenho tentou criar a PT com `respostas={}` — e `criar_pt` barrou, porque
`validar_respostas` roda na escrita. A tentação era afrouxar a criação "só para a IA".

Seria um buraco: `avaliar_pt` **não** cobre completude de formulário, então um rascunho
incompleto andaria o fluxo inteiro sem nada barrar. E abrir uma exceção para a IA daria ao
modelo um caminho por dentro da validação que uma pessoa não tem — o oposto da regra 1.

A saída foi tornar a divisão de trabalho explícita no contrato: medição e prazo entram pelo
pedido, texto vem do modelo. Como o tipo é escolhido pela IA, as respostas enviadas podem não
servir para ele — e aí volta o mesmo `409` com a lista de campos que faltam que qualquer PT
receberia, sem criar nada. Tem teste.

---

## L11 — Indicadores e alertas (2026-08-08)

**Entregue:** `GET /indicadores`, `GET /alertas` e `POST /alertas/sincronizar`, com cinco tipos
de alerta e escalonamento por tempo vencido.
**Aceite:** 195 testes passando (26 novos). Contra o banco de desenvolvimento, a sincronização
abriu o alerta da NR-35 vencida do Rafael Souza, já no nível 2 (OIM), e rodá-la de novo não
mudou nada.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/rules/alertas.py` | condições e escada de escalonamento, funções puras sem banco |
| `app/rules/exigencias.py` | prazos e a escada como dado: 2 h, 24 h, 8 h por nível |
| `app/services/alertas.py` | `sincronizar()` idempotente, `listar()` com escopo |
| `app/services/indicadores.py` | as contagens, todas no escopo |
| `app/routers/indicadores.py`, `app/schemas/indicadores.py` | painel e sincronização |
| `app/models/auditoria.py` + migration | `alerta` ganha `unidade_id`, `mensagem` e UNIQUE de identidade |
| `tests/test_alertas.py` | 26 testes |

### Decisões

- **Condição calculada, alerta gravado.** A condição vem do estado atual e some sozinha quando
  o problema é resolvido; o alerta guarda o que só o banco guarda — que já subiu de nível e
  desde quando dói. Os dois passos existem porque as duas coisas são diferentes.
- **Não há daemon.** `sincronizar()` é uma função que alguém chama — um cron, um botão, um
  teste. Prometer disparo automático num sistema sem agendador seria mentira; assim o que
  falta é uma linha de crontab, e está escrito.
- **Idempotente por construção.** A identidade do alerta é `(tipo, entidade, entidade_id)` com
  UNIQUE no banco, e o nível é função do relógio, não contador. Rodar mais vezes não inflaciona
  a urgência de nada.
- **Resolvido, nunca apagado.** Condição que some marca o alerta como resolvido. Apagar
  esconderia que o problema existiu — que é exatamente o que uma investigação vai procurar.
- **`unidade_id` no próprio alerta.** Deduzir da entidade obrigaria o filtro de escopo a saber
  se está olhando uma PT ou uma certificação. Guardado, a regra 5 é um `WHERE` só.
- **`responsavel` é derivado do nível, não gravado.** Gravar criaria uma segunda verdade: bastaria
  a escada mudar em `exigencias.py` para linhas antigas apontarem para quem não responde mais.
- **`sincronizar` ignora o escopo de quem chama** e é restrita a coordenação e OIM. Alerta que
  só existe quando a pessoa certa clica não é alerta.
- **P11 resolvida:** `AlertaRead` estava órfã desde o L1 e agora tem consumidor.

### O defeito que só apareceu rodando de verdade

A suíte passou 25/25 de primeira. Contra o banco de desenvolvimento, o primeiro alerta que saiu
foi `certificacao_a_vencer: NR-35 de Rafael Souza vence em 23/06/2026` — data passada, verbo no
futuro. A certificação não está *a vencer*, está *vencida* há mais de um mês.

O motor do L4 já separa `certificacao_vencida` de `certificacao_a_vencer`; meu vocabulário de
alertas tinha divergido do dele. Corrigido nos dois lugares (tipo e mensagem), com teste. Na
ressincronização o alerta errado foi **resolvido** e o certo abriu — o comportamento que o
desenho previa, confirmado no banco real.

**Terceira vez que rodar a aplicação pega o que a suíte não pega**, e pelo mesmo motivo: o teste
monta o cenário que eu imaginei; o banco de desenvolvimento carrega o que sobrou de sete loops.

### A quarta ferramenta de IA que eu não adicionei

Um `indicadores` como ferramenta do L9 fecharia uma brecha real da regra 2: hoje, perguntado
"quantas PTs a quente venceram este mês?", o modelo tenderia a somar resultados de busca.

Não entrou, e o teste que fixa o conjunto de três ferramentas fez o trabalho dele — me obrigou a
pensar antes. O motivo de não entrar é um conflito de verdade: uma resposta baseada só em
contagem não recupera PT nenhuma, e a regra 3 **como está implementada** descartaria o texto e
responderia "não encontrei". Resolver isso é decidir o que conta como fonte, e essa decisão é
do William. Fica como P40.

---

## L12 — PWA e operação offline (2026-08-08)

**Entregue:** as telas de verdade (login, lista, detalhe com formulário dinâmico e fluxo,
painel), manifesto, service worker, fontes locais e — o que dá nome ao loop — sincronização
que não atropela em silêncio.
**Aceite:** 213 testes passando (18 novos), incluindo o **teste obrigatório do contrato**.
Contra o banco de desenvolvimento: a segunda edição sobre uma leitura velha foi recusada com
`edicao_desatualizada` e o que estava gravado continuou gravado.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/services/permissoes.py` | `atualizar_pt` confere `visto_em` antes de gravar |
| `app/schemas/permissao.py` | `visto_em` obrigatório no `PermissaoTrabalhoUpdate` |
| `app/main.py` | rota `GET /sw.js`, servida da raiz para o escopo cobrir a aplicação |
| `static/index.html`, `static/js/app.js` | shell e a aplicação inteira (roteador, telas, fila) |
| `static/css/aegis.css` | sistema visual: tokens, `@font-face`, componentes |
| `static/sw.js` | shell cache-first, dados network-first, escrita nenhuma |
| `static/manifest.webmanifest`, `static/icons/` | instalação e ícones (comum + maskable) |
| `static/fonts/` | Oswald e JetBrains Mono locais, com a licença OFL junto |
| `tests/test_offline.py`, `tests/test_pwa.py` | 18 testes |

### O teste obrigatório, e por que `versao` não servia

O contrato exige desde o L0: *sincronização offline nunca sobrescreve mudança remota em
silêncio*. Hoje a edição não tinha controle nenhum — dois clientes no mesmo rascunho, o
último gravava por cima.

O reflexo era usar `versao` como token de concorrência. Não funciona: `versao` é a revisão
assinável do documento e **só sobe quando a PT sai do rascunho**, então entre duas edições de
rascunho ela não muda e não detectaria nada. Quem muda a cada escrita é `atualizado_em`.

Daí `visto_em`: o cliente devolve o `atualizado_em` que leu, e o servidor recusa se a PT
andou nesse meio-tempo. Obrigatório, não opcional — cliente que não diz o que viu não tem
como afirmar que não atropelou ninguém. Quebra de contrato no `PATCH`, declarada; três testes
antigos foram ajustados.

### Decisões

- **Ler é offline, assinar não.** Transição exige rede de propósito: o veredito do motor vale
  no instante da transição, e enfileirar uma liberação faria alguém sair da tela acreditando
  que autorizou um serviço que o servidor ainda pode recusar. A tela diz isso, não esconde.
- **A fila não resolve conflito sozinha.** Item que volta `409` fica marcado e aparece na tela
  da própria PT, com a opção de descartar. Reenviar por conta própria seria escolher um
  vencedor no escuro.
- **O service worker não vê escrita.** Só `GET`, e `/auth` fora do cache — token em cache é
  credencial deixada no disco de um tablet compartilhado. Dado servido da cópia local vem com
  `X-Aegis-Do-Cache` e a tela avisa: ninguém decide a partir de número velho achando que é de
  agora.
- **Fontes embarcadas.** Sem CDN em produção, fonte que só carrega online é identidade que
  desaparece justamente offshore. 65 KB, licença OFL junto (P1 resolvida).
- **`GET /sw.js` na raiz.** Em `/static/` o escopo do worker seria `/static/` e ele não
  controlaria a aplicação. Com `Cache-Control: no-cache`, senão o navegador serve um worker
  velho e a atualização nunca chega ao tablet.

### O que a skill de design achou

`/impeccable audit` acusou três ocorrências do mesmo padrão: barra de cor na lateral do
cartão — o tique mais reconhecível de interface gerada por IA. Corrigidas, e a correção
melhorou a acessibilidade em vez de só agradar o detector: onde a barra carregava informação
(nível do alerta), o nível passou a ser **escrito num chip**, porque cor sozinha não serve
para quem não distingue âmbar de vermelho nem para quem está no sol do convés.

Na mesma revisão saíram mais três: `cursor: pointer` em cartão que não clica, foco visível
só por mudança de borda (fina demais no escuro) e um bloco `prefers-reduced-motion` que era
código morto — não há animação nenhuma nesta folha. Detector limpo no fim.

---

## L13 — Auditoria de segurança e fechamento (2026-08-08)

**Entregue:** o endurecimento (cabeçalhos, limite de tentativas, conferência de conteúdo de
anexo, assinatura sobre leitura atual, erro sem stack) e a **auditoria** — cada pendência
declarada do L0 ao L12 resolvida em correção com teste ou risco aceito por escrito.
**Aceite:** 232 testes passando (19 novos). Contra a aplicação rodando: a sexta tentativa de
senha responde 429 com `Retry-After`, um executável `MZ` renomeado para `.pdf` é recusado no
primeiro bloco, e todos os cabeçalhos saem — inclusive nas respostas de erro.

### Arquivos tocados

| Arquivo | Papel |
|---|---|
| `app/security/cabecalhos.py` | CSP e demais cabeçalhos, em middleware |
| `app/security/limite.py` | janela deslizante por origem e identidade |
| `app/security/arquivos.py` | assinatura dos formatos aceitos |
| `app/services/anexos.py` | conferência do primeiro bloco antes de gravar |
| `app/services/transicoes.py`, `app/schemas/permissao.py` | `visto_em` opcional na transição |
| `app/routers/auth.py`, `app/routers/ai.py` | limites aplicados |
| `app/main.py` | middleware e handler genérico de erro |
| `static/js/app.js` | o PWA passa a enviar `visto_em` ao assinar |
| `docs/SECURITY.md` | **a auditoria**: 17 pendências resolvidas em corrigido ou aceito |
| `tests/test_endurecimento.py` | 19 testes |

### Decisões

- **CSP sem `unsafe-inline` nem `unsafe-eval`.** O produto permite ser rígido: PWA vanilla, sem
  framework, sem build e sem CDN, então não existe script inline para acomodar.
- **Isso e o token no `localStorage` são uma decisão só, não duas.** Guardar o token ali só é
  defensável porque não há script de terceiro e a CSP proíbe um. Estão documentados juntos de
  propósito: **relaxar `script-src` transforma o risco aceito em defeito.**
- **Limite por origem *e* identidade.** Só por IP puniria a unidade inteira atrás de um NAT; só
  por matrícula deixaria varrer contas diferentes da mesma origem. O acerto zera a contagem.
- **Conferência de conteúdo antes da de tamanho.** Aborta um arquivo de tipo errado depois de
  64 KB em vez de ler até o limite. Custou ajustar um teste antigo que mandava bytes de
  enchimento sem cabeçalho `%PDF-`.
- **`visto_em` obrigatório na edição, opcional na transição.** Na edição impede sobrescrita; na
  transição impede que uma assinatura valha por um documento que mudou depois de lido. Torná-lo
  obrigatório quebraria todo cliente existente por uma garantia que é melhoria, não correção.

### O que a auditoria decidiu não corrigir, e por quê

Sete pendências ficaram como **risco aceito**, cada uma com o motivo escrito na tabela de
`docs/SECURITY.md`. As que mais valem repetir:

- **Sem lista de revogação de token.** O token não carrega perfil: perfil e lotação são lidos do
  banco a cada requisição, então revogar acesso vale na hora. O que sobrevive é a identidade,
  por no máximo um turno. Uma lista de revogação exige estado compartilhado entre processos.
- **Injeção de prompt pelo conteúdo da PT.** Revisada aqui: não faz o modelo agir — não há
  ferramenta que escreva, e as fontes vêm do banco, não da resposta. Influencia a redação.
  Contenção estrutural vale mais que endurecimento de prompt, e a estrutura já está posta.
- **Trilha por PT, sem cadeia global.** É desenho: o documento é o que uma investigação
  reconstrói. Trilha de login é outro artefato, com outra pergunta de retenção.

Dois limites valem para a tabela inteira e estão escritos lá: os limitadores são **em processo**
(com vários workers, o limite efetivo multiplica), e **não houve teste de invasão** — isto é
auditoria de código e desenho feita por quem escreveu o código, e vale o que isso vale.

### Pendências abertas

| # | Pendência | Loop de destino |
|---|---|---|
| ~~P1~~ | ~~Fontes só em fallback de sistema~~ — Oswald e JetBrains Mono embarcadas em `static/fonts/`, com a OFL junto | resolvido no L12 |
| ~~P2~~ | ~~Sem manifesto e sem service worker~~ — `manifest.webmanifest`, ícones e `sw.js` na raiz | resolvido no L12 |
| ~~P3~~ | ~~Sem cabeçalhos, sem rate limiting, erro com stack~~ — os três entregues | resolvido no L13 |
| ~~P4~~ | ~~Dependências de auth~~ — `argon2-cffi` e `pyjwt` no `requirements.txt` | resolvido no L2 |
| ~~P5~~ | ~~Dependências de IA no `requirements.txt`~~ — `anthropic>=0.121`; índice vetorial não foi preciso, as ferramentas consultam o banco | resolvido no L9 |
| P6 | `starlette.testclient` avisa que `httpx` está depreciado em favor de `httpx2` — sem efeito hoje | reavaliar em L13 |
| ~~P7~~ | ~~Repositório sem remote~~ — publicado em TheAlphaOffshoreCode/aegis-pt, CI verde | resolvido em 05/08/2026 |
| ~~P8~~ | ~~`security-review` sem linha de base~~ — destravada pelo commit inicial | resolvido em 05/08/2026 |
| ~~P9~~ | ~~`impeccable` nunca aplicada a tela real~~ — telas construídas e auditadas; detector limpo | resolvido no L12 |
| ~~P10~~ | ~~Coluna `respostas` especulativa~~ — virou o campo onde o formulário dinâmico grava | resolvido no L3 |
| ~~P11~~ | ~~`AlertaRead` sem consumidor~~ — `/alertas` entregue, com `mensagem`, `unidade_id` e `responsavel` derivado | resolvido no L11 |
| ~~P12~~ | ~~`usuario` sem credencial~~ — `senha_hash`, `ultimo_acesso` e `unidade_id` criados | resolvido no L2 |
| P13 | Compatibilidade com Python 3.11 só é provada no CI — esta máquina tem apenas 3.14 | contínuo |
| P14 | Login com limite desde o L13 (5/min por origem e matrícula). Continua **sem lista de revogação**: token vazado vale até vencer, no máximo um turno — risco aceito e justificado em `docs/SECURITY.md` | aceito no L13 |
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
| ~~P30~~ | ~~Só a extensão validada~~ — assinatura conferida no primeiro bloco; provado com um `MZ` renomeado | resolvido no L13 |
| P21 | Duração máxima e pares incompatíveis são constantes em `exigencias.py`. Se a operação quiser ajustar sem deploy, viram configuração | quando pedirem |
| P22 | API aceita datetime sem fuso e o trata como UTC. Exigir offset explícito é decisão do contrato HTTP | L12/L13 |
| P32 | **O caminho real contra a Claude API não foi exercitado**: esta máquina não tem chave. Provado o que dá — laço, escopo, fontes e 503 — com cliente falso e com a aplicação no ar. Falta uma consulta de verdade | assim que houver chave |
| P33 | Injeção via conteúdo de PT — **revisada e aceita** no L13: não faz o modelo agir, influencia redação. A contenção é estrutural e já está posta | aceito no L13 |
| ~~P34~~ | ~~`/ai/consulta` sem limite de uso~~ — 20/min por pessoa e origem | resolvido no L13 |
| P35 | A consulta por IA não entra na trilha. Quem perguntou o quê pode ser registro que a auditoria vai querer — esbarra em P26 (evento sem PT não tem cadeia) | L13 |
| P36 | Fallback de modelo (beta) não implementado: numa recusa ou indisponibilidade, a consulta falha em vez de tentar outro modelo. Deliberado — trocar quem responde sobre segurança é decisão do William | quando o William decidir |
| P37 | **Rascunho não pode nascer incompleto.** `validar_respostas` vive na escrita (`criar_pt`/`atualizar_pt`), não em `avaliar_pt` — por isso a medição entra junto com o pedido. Se a operação quiser abrir a PT *antes* de medir, a completude precisa migrar para o motor de regras e passar a barrar a transição, não a criação | decisão de produto |
| P38 | Perigo e controle são duas listas de frases (`[{"descricao": ...}]`), sem vínculo entre si. Amarrar cada controle ao perigo que ele mitiga é o que uma tela de análise vai querer | L11/L12 |
| ~~P39~~ | ~~`/ai/rascunho` sem limite~~ — mesmo limitador da P34 | resolvido no L13 |
| P40 | **Ferramenta `indicadores` para a IA**, que fecharia a brecha de o modelo somar resultados de busca. Esbarra na regra 3 como implementada: resposta sem PT recuperada é descartada. Exige decidir o que conta como fonte | decisão do William |
| ~~P41~~ | ~~Nada agenda a sincronização de alertas~~ — `python -m app.sincronizar_alertas`, com as linhas de `cron` e `schtasks` no docstring e no README | resolvido em 10/08/2026 |
| P42 | `sincronizar()` varre todas as PTs não encerradas e todas as certificações a cada chamada. Com acervo grande vira leitura completa por passagem — mesma família da P27 | quando o acervo crescer |
| P43 | Alerta não tem reconhecimento humano: só `resolvido` automático pela condição sumir. Não dá para dizer "vi, estou tratando", e o `CANCELADO` do enum não tem caminho de código | quando a operação pedir |
| P44 | Transição não é enfileirada offline, por decisão. Se a operação precisar assinar sem sinal, exige repensar onde o motor de regras roda — não é ajuste de fila | decisão de produto |
| P45 | Token no `localStorage` — **risco aceito condicionalmente**: só é defensável porque não há script de terceiro e a CSP proíbe um. Relaxar `script-src` transforma isto em defeito | aceito no L13 |
| P46 | Anexar arquivo offline não existe: a fila guarda correção de rascunho, não binário. Exigiria IndexedDB | quando pedirem |
| ~~P47~~ | ~~Assinar sobre leitura velha~~ — `visto_em` opcional na transição, recusa com `documento_alterado` | resolvido no L13 |
| P48 | Nenhum teste roda o JavaScript: não há runner no projeto. As telas foram verificadas com `node --check`, pelos contratos dos endpoints e rodando a aplicação | quando houver caso |
| P51 | **Suíte intermitente no Windows.** Numa de três execuções completas, `test_alertas.py::test_pt_em_execucao_com_janela_encerrada_gera_alerta_critico` deu **ERROR de fixture** (`250 passed, 1 error`); isolado e nas outras duas rodadas, passa. A fixture `db` faz `create_all`/`drop_all` sobre o mesmo `test_aegis.db` a cada teste, e o arquivo continua aberto pelo pool entre um e outro. Banco em memória ou por-arquivo temporário resolveria; não reproduzido ainda | quando reproduzir |

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

L10 fechado e verificado: 169 testes passando, nenhum saindo para a rede. Com a aplicação no
ar e sem chave, `/ai/rascunho` responde 503 e `/pts` segue devolvendo as 2 PTs do banco de
desenvolvimento.

L11 fechado e verificado: 195 testes passando. No banco de desenvolvimento, `sincronizar`
abriu o alerta da NR-35 vencida no nível 2 (OIM) e a segunda chamada não mudou nada; o painel
responde 2 PTs no escopo, uma em `LIBERACAO` e uma em `RASCUNHO`.

**Para manter os alertas vivos:** algo precisa chamar `POST /alertas/sincronizar`
periodicamente (P41). Não há agendador no processo, de propósito.

L13 fechado e verificado: **232 testes passando**. Contra a aplicação rodando, a sexta
tentativa de senha responde 429 com `Retry-After`, um executável renomeado para `.pdf` é
recusado no primeiro bloco e todos os cabeçalhos saem, inclusive nas respostas de erro.

## O contrato está cumprido

**L0 a L13 concluídos.** Todo o escopo planejado no L0 foi entregue, e as oito regras
invioláveis têm teste que falha se alguma sair.

O que sobra não é dívida escondida — está tudo na tabela acima e, com o motivo, na tabela de
`docs/SECURITY.md`:

- ~~**Uma pendência operacional (P41)**~~ — resolvida em 10/08/2026 com
  `python -m app.sincronizar_alertas`, que é o que o agendador chama.
- **Duas decisões de produto esperando o William:** a ferramenta `indicadores` para a IA (P40)
  e se o rascunho pode nascer incompleto (P37).
- **Sete riscos aceitos por escrito**, cada um com o porquê.
- **Um loop proposto e nunca aberto: L8.5 — Acervo legado e OCR.** Continua sendo o caminho
  para o acervo em papel: modelo `documento_legado`, ingestão em lote, OCR com Tesseract,
  indexação e vínculo com PT. Entra hoje como mais uma ferramenta somente-leitura da IA, sem
  mexer no laço.

Para retomar em qualquer um deles, o ponto de partida é a tabela de pendências desta página. Escopo próprio: modelo `documento_legado`,
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

---

## Fora de loop — verificação independente (09/08/2026)

Repositório clonado noutro PC, dependências reinstaladas e a aplicação **rodada de verdade**:
migrations, seed, `uvicorn`, uma PT criada e levada até `VALIDACAO`, e o PWA dirigido num Chrome
por CDP. Dois defeitos, um em cada ponta do que a suíte não alcança.

**P49 — a cadeia de auditoria bifurcava sob concorrência.** `registrar_evento` lê o último elo e
depois insere, sem trava, restrição ou isolamento entre as duas coisas. Duas gravações
simultâneas na mesma PT — anexo e assinatura no mesmo instante — leem o mesmo `hash_anterior` e
nascem irmãs; a cadeia bifurca e o verificador passa a acusar adulteração para sempre numa trilha
que ninguém tocou. O SQLite esconde pela trava global de escrita, então só apareceria no
PostgreSQL de produção. Corrigido com `UNIQUE (pt_id, hash_anterior)` (migration
`ccddf73c09f2`); o perdedor da corrida leva `IntegrityError` e a requisição falha, que é ruidoso
mas honesto. Teste novo em `test_auditoria.py`, provado a desligar a restrição e ver o teste cair.

**P50 — o veredito do motor de regras nunca chegou à tela.** `GET /pts/{id}/pendencias` devolve a
avaliação inteira (`AvaliacaoRead`) e o detalhe iterava a resposta direto: `.length` saía
`undefined`, o `for...of` estourava no objeto e o `catch` virava um aviso amarelo com cara de
falha de rede. Em toda PT, desde o L4. Corrigido com uma desestruturação, e conferido na tela
antes e depois.

O P48 (nenhum teste roda o JavaScript) era risco aceito com uma mitigação declarada — "os
contratos dos endpoints que as telas consomem" — que nunca tinha sido escrita. O P50 é exatamente
ela cobrando. Agora existe: `test_pwa.py` casa cada `api()` do `app.js` contra o OpenAPI vivo da
aplicação, e o teste afirma quantas chamadas conferiu, para não se desligar em silêncio se o
regex quebrar. Comportamento de tela — renderização, roteamento, fila offline — segue sem
cobertura.

**247 testes passando** (2 novos). Auditoria completa, incluindo o que foi conferido e nada tinha:
sem injeção de SQL, sem segredo no código, sem `eval`/`subprocess`; upload, download, JWT, Argon2,
escopo e ferramentas da IA todos íntegros.

---

## Fora de loop — a tela fecha o ciclo (09/08/2026)

Ao abrir a aplicação, o William notou que ela parecia servir só para **consultar** PTs já
existentes. Estava certo: a interface tinha quatro rotas (login, lista, detalhe, painel) e
consumia 8 dos 21 endpoints. Emitir uma PT e anexar documento existiam no backend, com teste e
documentação, e não tinham tela. O sintoma mais afiado era o detalhe mostrar "documento APR não
foi anexado — bloqueante" sem oferecer nenhum jeito de anexar: a tela informava um impedimento
que ela mesma não deixava resolver.

### Entregue

- **`GET /areas`** — áreas do escopo de quem pergunta. Nasceu por necessidade: `area_id` é
  obrigatório na PT e não havia de onde tirá-lo sem consultar o banco por fora. Escopo na
  consulta, como todo o resto: código e nome de área já dizem o que existe a bordo.
- **`GET /pts/modelos`** — um modelo ativo por tipo, o de maior versão.
- **Tela de emissão** (`#/nova`), com o formulário dinâmico do modelo escolhido.
- **Bloco de anexos** no detalhe: listar, enviar, baixar e remover (remoção só no rascunho, e o
  servidor confere de novo).

### Decisões

- **O seletor de tipo sai de `/pts/modelos`, não do enum.** Descoberto rodando: a primeira
  versão oferecia os seis `TipoTrabalho` e o seed só tem dois modelos. Escolher
  `espaco_confinado` levava a "formulário indisponível" e a emissão morria ali. Oferecer só o
  que dá para emitir é o seletor dizendo a verdade — e de quebra sumiu a lista fixa de tipos no
  JavaScript, que era uma segunda cópia do enum livre para divergir.
- **A unidade sai da área escolhida, não do usuário.** Admin não tem lotação, e é a área que
  sabe a que unidade o trabalho pertence.
- **Emitir exige rede**, como assinar transição. O número da PT é do servidor; sair da tela com
  uma PT que ainda não existe é pior do que não emitir.
- **`datetime-local` é convertido para UTC antes de sair** (`instanteUtc`). O campo entrega
  hora sem fuso e a API trata data sem fuso como UTC — enviar cru faria a janela de validade de
  uma PT emitida no Brasil nascer três horas fora do lugar. Janela de validade é número de
  segurança.
- **`api()` não escreve `Content-Type` quando o corpo é `FormData`.** Quem conhece o `boundary`
  é o navegador; declarar `application/json` faria o upload chegar como um corpo ilegível.
- **`/areas` fica fora do cache do service worker.** A lista serve à emissão, que exige rede de
  qualquer forma: guardá-la seria pôr no disco do tablet o que existe a bordo em troca de nada.
- **O download do anexo entra no documento antes do clique e revoga o blob depois.** Âncora
  solta com revogação imediata funciona no Chrome e falha calada em outros navegadores — o
  arquivo não desce e nada aparece na tela.

### Aceite

**251 testes passando** (3 novos). O escopo de `/areas` foi provado nos dois sentidos:
desligando o filtro, o teste cai. Fluxo conferido na aplicação de verdade, num Chrome dirigido
por CDP: PT-2026-0002 emitida pela tela, APR anexada, e a pendência bloqueante mudou de APR para
ASO — o motor de regras respondendo à ação feita na interface.

Duas recusas legítimas apareceram no caminho e valem registro, porque são a proteção
funcionando: emitir sem preencher campo obrigatório do modelo devolveu `409` com a pendência
nomeando o campo, e o tipo sem modelo foi barrado antes do envio.

### O que continua sem tela

`GET /pts/{id}/trilha` (a trilha, que é a justificativa do produto), dossiê, versões, evento
compensatório, `POST /ai/consulta` e `POST /ai/rascunho` — os dois loops de IA inteiros — e
`POST /alertas/sincronizar` (o P41). Nada disso é novo; o que muda é que agora está escrito.

---

## Fora de loop — a trilha na tela e o agendador (10/08/2026)

Duas coisas da lista acima, escolhidas por serem as que doíam: a trilha é a justificativa do
produto e não aparecia em lugar nenhum, e o quadro de alertas dependia de uma linha de crontab
que ninguém tinha escrito.

### Entregue

- **Bloco "Trilha de auditoria"** no detalhe da PT: o veredito da cadeia em palavras
  (`cadeia íntegra · N elos`, ou onde ela deixou de fechar) e cada elo com momento, tipo de
  evento, mudança de estado, perfil do ator, motivo e as duas pontas do hash.
- **`python -m app.sincronizar_alertas`** — a P41. Uma passagem, idempotente, com as linhas de
  `cron` e de `schtasks` no docstring do módulo e no README.

### Decisões

- **`<details>` nativo, fechado, que só busca ao abrir.** Recolher e expandir sem uma linha de
  JavaScript, com teclado e leitor de tela já resolvidos pelo navegador. E a trilha não é o que
  se lê para decidir agora: é a resposta mais longa que esta tela pede, e cobrá-la em toda
  abertura de PT sairia caro no enlace de bordo.
- **O tipo de evento vai cru, como o servidor gravou.** O catálogo de tipos é aberto por
  desenho (foi assim que `pt.criada_por_ia` entrou sem bump de `VERSAO_PAYLOAD`). Traduzir os
  nomes na tela criaria uma segunda cópia dele, livre para divergir — e um tipo novo apareceria
  em branco em vez de aparecer pelo nome.
- **O veredito é escrito, não só colorido.** Mesma regra do chip de nível do L12: cor sozinha
  não serve para quem não distingue as cores nem para quem está no sol do convés.
- **`carregada` só é marcada no sucesso.** A trilha é append-only, então o que já está na tela
  continua valendo; mas uma falha de rede tem de poder ser repetida fechando e reabrindo.
- **O comando do agendador vai ao banco, não à rota.** `POST /alertas/sincronizar` continua
  servindo ao botão da tela, e é restrita a coordenação e OIM: um cron chamando-a precisaria de
  uma credencial de serviço guardada no servidor, com rotação e risco de vazar — uma conta de
  máquina com poder de escrita, inventada para resolver agendamento. O comando já está do lado
  de dentro do banco e não inventa credencial nenhuma. Escopo não é problema: `sincronizar`
  ignora o escopo de quem chama desde o L11, de propósito.

### Aceite

**252 testes passando** (1 novo). O teste do entrypoint foi provado nos dois sentidos:
trocando a chamada de `sincronizar(db)` por um resultado vazio, ele cai; restaurado, passa.

Contra o banco de desenvolvimento, o comando rodou duas vezes seguidas — a primeira abriu 1
alerta, a segunda não mexeu em nada, que é a idempotência prometida no L11 valendo pelo caminho
novo.

A trilha foi conferida no Chrome dirigido por CDP, em 390 px: login pela tela, detalhe da
`PT-2026-0001`, clique de verdade no `summary` e os dois elos na tela — `pt.criada` e
`pt.transicao.validacao`, com `início → 59b6b082560e` e `59b6b082560e → b73a79a08425`, o
segundo abrindo com o que o primeiro fechou. Nenhum aviso de erro na tela e nada no console.

### O que continua sem tela

Dossiê, versões, evento compensatório e os dois loops de IA. A trilha saiu da lista.

---

## Fora de loop — o shell misturado (10/08/2026)

Aberta a aplicação para ver a trilha, **a aba EMITIR não fazia nada**. A tela estava certa: num
Chrome limpo ela abre. O que estava errado era o que o navegador tinha guardado — `index.html`
novo (com a aba) e `app.js` velho (sem a rota `nova`), e o roteador antigo cai no `else` final e
redesenha a lista. Clicar parecia não fazer nada porque, literalmente, a mesma tela voltava.

**Como o shell se mistura.** O cache-first do L12 revalida em segundo plano, e revalida *por
arquivo*: quem abre e fecha rápido atualiza alguns e deixa outros para trás. Na visita seguinte o
cache tem duas gerações ao mesmo tempo, e a `VERSAO` — escrita à mão desde o L12 — não muda
sozinha para dizer que aquilo virou outro aplicativo. Já estava escrito no `CLAUDE.md` que
depender de lembrar de trocá-la era depender de memória humana para uma falha silenciosa; foi
essa a conta chegando.

### Entregue

- **`GET /sw.js` injeta a versão**, calculada como resumo SHA-256 do conteúdo de `static/`
  (menos o próprio `sw.js`, que carrega o valor e não pode depender de si mesmo). Conteúdo
  diferente, versão diferente, cache refeito inteiro — e o `activate`, que já apagava caches de
  outra versão, passa a ter o que apagar.
- **`install` busca com `cache: "reload"`.** Sem isso o `addAll` pode ser atendido pelo cache
  HTTP do próprio navegador, e a instalação da versão nova guardaria os arquivos velhos.

### Aceite

**254 testes** (2 novos): a rota entrega uma versão substituída, e a impressão digital muda
quando um arquivo do shell muda e **não** muda quando só o `sw.js` muda.

Provado num Chrome com perfil persistente, que é o que representa o tablet: instalado o
aplicativo (`aegis-982a5275b4cd`), acrescentei um marcador ao `app.js`, e na carga seguinte o
navegador trocou de worker sozinho (`aegis-1ae553f13614`), refez o cache e passou a servir o
arquivo novo — com o cache antigo apagado, sem sobrar mistura. Restaurado o `app.js` por cópia, a
versão voltou exatamente ao valor anterior, que é a impressão digital fazendo o que promete.

**Para quem já tem o aplicativo aberto**, um `Ctrl+Shift+R` resolve na hora; sem ele são duas
recargas — a primeira troca o worker, a segunda carrega a página com o shell novo.

### A segunda causa, encontrada porque o sintoma voltou

Com o worker corrigido, a aba continuou sem responder. O que faltava não passava pelo service
worker: **o shell não mandava `Cache-Control` nenhum.** Sem a diretiva, o Starlette envia só
`ETag` e `Last-Modified`, e vale a heurística do navegador — ele reusa o arquivo sem perguntar
por uma fração do tempo desde a última modificação. Como cada arquivo tem a sua própria idade,
saem do frescor em momentos diferentes, e o `index.html` novo volta a encontrar o `app.js`
velho. A mesma mistura, por um caminho onde o worker nunca é consultado.

`/`, `/static/*` e `/sw.js` passam a sair com `no-cache`, que não proíbe guardar: obriga a
perguntar. Com o `ETag` que já saía, a confirmação é um `304` sem corpo.

**259 testes.** Cinco novos, e o que mais importa é o do `304`: é ele que responde em toda
recarga, e uma diretiva que só aparecesse no `200` deixaria justamente a resposta do dia a dia
sem instrução nenhuma. Todos provados nos dois sentidos — desligando a sobrescrita, caem.
