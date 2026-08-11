/* AEGIS PT — aplicação. Vanilla, sem framework e sem build: o que está aqui é o que roda.
 *
 * A decisão que organiza o resto: **leitura funciona offline, escrita depende do caso.**
 *
 * - Ler é offline por completo — o service worker guarda o que já passou pela tela.
 * - Corrigir rascunho vai para uma fila e sai quando o sinal volta, levando junto o
 *   `visto_em` da leitura que originou a correção. Se a PT mudou nesse meio-tempo, o servidor
 *   recusa e a tela mostra o conflito. Nada é reenviado por cima em silêncio.
 * - Assinar transição **exige rede**, de propósito. O veredito do motor de regras vale no
 *   instante da transição; enfileirar uma liberação faria alguém sair da tela acreditando que
 *   autorizou um serviço que o servidor ainda vai recusar.
 */

const API = {
  token: localStorage.getItem("aegis_token"),
  // De quem é a sessão atual. O tablet do convés é compartilhado, então "quem está logado"
  // não é uma pergunta retórica: dela dependem o que o cache pode devolver e o que a fila
  // pode enviar.
  matricula: localStorage.getItem("aegis_matricula"),
  usuario: null,
};

/** Apaga a cópia local de dados autenticados.
 *
 * Chamada em toda troca de identidade. Sem isto, quem entrasse depois leria offline as PTs de
 * quem entrou antes: o service worker guarda por URL, e a URL não tem dono.
 */
async function limparCacheDeDados() {
  if (!("caches" in window)) return;
  const nomes = await caches.keys();
  await Promise.all(nomes.filter((n) => n.endsWith("-dados")).map((n) => caches.delete(n)));
}

const tela = document.getElementById("tela");
const abas = document.getElementById("abas");
const chipConexao = document.getElementById("conexao");
const chipFila = document.getElementById("fila");

/* --- utilidades de DOM ----------------------------------------------------------------- */

function el(tag, atributos = {}, filhos = []) {
  const no = document.createElement(tag);
  for (const [chave, valor] of Object.entries(atributos)) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (chave === "class") no.className = valor;
    else if (chave === "texto") no.textContent = valor;
    else if (chave.startsWith("on")) no.addEventListener(chave.slice(2), valor);
    else no.setAttribute(chave, valor);
  }
  for (const filho of [].concat(filhos)) {
    if (filho) no.append(filho);
  }
  return no;
}

function linha(rotulo, valor) {
  return el("div", { class: "linha" }, [
    el("dt", { texto: rotulo }),
    el("dd", { texto: valor === null || valor === undefined ? "—" : String(valor) }),
  ]);
}

function aviso(texto, tipo = "", titulo = "") {
  return el("div", { class: `aviso ${tipo}` }, [
    titulo ? el("div", { class: "titulo", texto: titulo }) : null,
    el("div", { texto }),
  ]);
}

function instante(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

/* --- chamada à API --------------------------------------------------------------------- */

class ErroDaApi extends Error {
  constructor(status, corpo) {
    super(ErroDaApi.mensagem(status, corpo));
    this.status = status;
    this.pendencias = Array.isArray(corpo?.detail) ? corpo.detail : [];
  }

  static mensagem(status, corpo) {
    if (Array.isArray(corpo?.detail)) {
      // Duas listas diferentes chegam aqui. O `409` traz pendências do motor de regras
      // (`mensagem`, `codigo`); o `422` traz erros do Pydantic, que usam `msg`. Sem esta
      // terceira alternativa o `map` devolvia `undefined` para cada item e o `join` entregava
      // string vazia — a tela abria a caixa vermelha **sem texto nenhum**, e o caso é banal:
      // basta emitir uma PT com a janela de validade invertida.
      return corpo.detail.map((p) => p.mensagem || p.codigo || p.msg).join(" · ");
    }
    return corpo?.detail || `Erro ${status}`;
  }
}

async function api(caminho, opcoes = {}) {
  const cabecalhos = { ...(opcoes.headers || {}) };
  if (API.token) cabecalhos.Authorization = `Bearer ${API.token}`;
  // `FormData` fica de fora: quem tem de escrever o `Content-Type` é o navegador, porque só
  // ele conhece o `boundary` que separa as partes. Declarar `application/json` aqui faria o
  // upload de anexo chegar ao servidor como um corpo que ninguém consegue ler.
  if (opcoes.body && !(opcoes.body instanceof FormData)) {
    cabecalhos["Content-Type"] = "application/json";
  }

  const resposta = await fetch(caminho, { ...opcoes, headers: cabecalhos });
  const corpo = resposta.status === 204 ? null : await resposta.json().catch(() => null);

  if (resposta.status === 401) {
    sair();
    throw new ErroDaApi(401, { detail: "Sessão encerrada. Entre de novo." });
  }
  if (!resposta.ok) throw new ErroDaApi(resposta.status, corpo);

  // O service worker marca o que veio da cópia local, para a tela poder dizer a idade do dado
  // em vez de deixar alguém decidir achando que é de agora.
  if (resposta.headers.get("X-Aegis-Do-Cache")) {
    Object.defineProperty(corpo, "__doCache", { value: true, enumerable: false });
  }
  return corpo;
}

/* --- fila de envio --------------------------------------------------------------------- */

/* Guardada em `localStorage` por simplicidade: são correções de rascunho, não anexos.
 * ponytail: se um dia entrar upload offline, isto vira IndexedDB — localStorage tem ~5 MB e
 * é síncrono. */
const Fila = {
  ler() {
    try {
      return JSON.parse(localStorage.getItem("aegis_fila") || "[]");
    } catch {
      return [];
    }
  },
  gravar(itens) {
    localStorage.setItem("aegis_fila", JSON.stringify(itens));
    Fila.pintar();
  },
  enfileirar(item) {
    const itens = Fila.ler();
    itens.push({
      ...item,
      id: Date.now(),
      enfileirado_em: new Date().toISOString(),
      // De quem é esta correção. Sem a marca, o item sairia com o token de quem estivesse
      // logado na hora do reenvio — e a trilha registraria a pessoa errada como autora.
      matricula: API.matricula,
    });
    Fila.gravar(itens);
  },

  /** Só o que pertence a quem está logado agora. */
  minhas() {
    return Fila.ler().filter((i) => i.matricula === API.matricula);
  },
  remover(id) {
    Fila.gravar(Fila.ler().filter((i) => i.id !== id));
  },
  marcarConflito(id, mensagem) {
    Fila.gravar(Fila.ler().map((i) => (i.id === id ? { ...i, conflito: mensagem } : i)));
  },
  pintar() {
    const itens = Fila.minhas();
    const conflitos = itens.filter((i) => i.conflito).length;
    chipFila.hidden = itens.length === 0;
    chipFila.textContent = conflitos
      ? `${conflitos} em conflito`
      : `${itens.length} na fila`;
    chipFila.className = `chip ${conflitos ? "bloqueante" : "offline"}`;
  },

  async enviar() {
    // `minhas()`, não `ler()`: item de outra pessoa sairia com o meu token, e a trilha
    // registraria a autoria errada numa PT.
    for (const item of Fila.minhas()) {
      // Item em conflito não é reenviado sozinho: quem decide o que fazer com ele é a pessoa,
      // na tela da PT. Reenviar por conta própria seria escolher um vencedor no escuro.
      if (item.conflito) continue;
      try {
        await api(item.caminho, { method: item.metodo, body: JSON.stringify(item.corpo) });
        Fila.remover(item.id);
      } catch (erro) {
        if (erro.status === 409) {
          Fila.marcarConflito(item.id, erro.message);
        } else if (erro.status >= 400 && erro.status < 500) {
          Fila.marcarConflito(item.id, erro.message);
        } else {
          // Rede ou servidor fora: fica na fila, tenta na próxima.
          return;
        }
      }
    }
  },
};

/* --- conexão --------------------------------------------------------------------------- */

function pintarConexao(online) {
  chipConexao.textContent = online ? "online" : "offline";
  chipConexao.className = `chip ${online ? "online" : "offline"}`;
}

async function aoReconectar() {
  pintarConexao(true);
  await Fila.enviar();
  rotear();
}

window.addEventListener("online", aoReconectar);
window.addEventListener("offline", () => pintarConexao(false));

/* --- telas ----------------------------------------------------------------------------- */

function telaLogin() {
  const matricula = el("input", { name: "matricula", inputmode: "numeric", required: "" });
  const senha = el("input", { name: "senha", type: "password", required: "" });
  const destino = el("div");

  const form = el("form", {
    onsubmit: async (evento) => {
      evento.preventDefault();
      destino.replaceChildren();
      try {
        const dados = await api("/auth/login", {
          method: "POST",
          body: JSON.stringify({ matricula: matricula.value, senha: senha.value }),
        });
        // Entrou outra pessoa neste aparelho: a cópia local da anterior não pode sobreviver.
        if (API.matricula && API.matricula !== matricula.value) {
          await limparCacheDeDados();
        }
        API.token = dados.access_token;
        API.matricula = matricula.value;
        localStorage.setItem("aegis_token", API.token);
        localStorage.setItem("aegis_matricula", API.matricula);
        Fila.pintar();
        location.hash = "#/pts";
      } catch (erro) {
        destino.append(aviso(erro.message, "erro", "Não foi possível entrar"));
      }
    },
  }, [
    el("label", {}, [el("span", { class: "rotulo", texto: "Matrícula" }), matricula]),
    el("label", {}, [el("span", { class: "rotulo", texto: "Senha" }), senha]),
    el("button", { type: "submit", texto: "Entrar" }),
  ]);

  return el("section", { class: "painel" }, [
    el("h2", { texto: "Identificação" }),
    destino,
    form,
  ]);
}

const ESTADOS = [
  "RASCUNHO", "VALIDACAO", "ANALISE_SMS", "APROVACAO", "LIBERACAO",
  "EM_EXECUCAO", "SUSPENSA", "ENCERRADA", "REJEITADA", "ARQUIVADA",
];

const TIPOS_ANEXO = ["apr", "aso", "certificado", "relatorio", "foto", "croqui"];

/** Converte o que o `datetime-local` devolve no instante UTC correspondente.
 *
 * O campo entrega `2026-08-09T20:46`, sem fuso, e a API trata data sem fuso como UTC. Enviar
 * o valor cru faria a janela de validade de uma PT emitida no Brasil nascer três horas fora do
 * lugar — e janela de validade é número de segurança, não detalhe de formatação.
 */
function instanteUtc(valorLocal) {
  return new Date(valorLocal).toISOString();
}

async function telaLista(parametros) {
  const secao = el("section");
  const busca = new URLSearchParams(parametros);
  const filtroEstado = busca.get("estado") || "";
  // As fontes citadas pela IA são números de PT, e o número é o que a pessoa reconhece. Chegar
  // por aqui faz a consulta passar pelo escopo de sempre, em vez de a tela resolver por fora.
  const filtroNumero = busca.get("numero") || "";

  const seletor = el("select", {
    onchange: (e) => {
      location.hash = e.target.value ? `#/pts?estado=${e.target.value}` : "#/pts";
    },
  }, [
    el("option", { value: "", texto: "Todos os estados" }),
    ...ESTADOS.map((e) =>
      el("option", { value: e, texto: e, selected: e === filtroEstado || null })
    ),
  ]);

  secao.append(
    el("section", { class: "painel" }, [
      el("h2", { texto: "Permissões de trabalho" }),
      el("label", {}, [el("span", { class: "rotulo", texto: "Filtrar" }), seletor]),
      filtroNumero
        ? el("p", { class: "vazio" }, [
            document.createTextNode(`Filtrando por ${filtroNumero} · `),
            el("a", { href: "#/pts", texto: "ver todas" }),
          ])
        : null,
    ])
  );

  try {
    const consulta = new URLSearchParams();
    if (filtroEstado) consulta.set("estado", filtroEstado);
    if (filtroNumero) consulta.set("numero", filtroNumero);
    const sufixo = consulta.toString() ? `?${consulta}` : "";
    const pagina = await api(`/pts${sufixo}`);
    if (pagina.__doCache) {
      secao.append(aviso("Sem conexão: esta lista é a última cópia recebida.", "", "Dado local"));
    }
    if (!pagina.itens.length) {
      secao.append(el("p", { class: "vazio", texto: "Nenhuma PT neste filtro." }));
    }
    for (const pt of pagina.itens) {
      secao.append(
        el("a", { class: "cartao", href: `#/pt/${pt.id}` }, [
          el("div", { class: "cabeca" }, [
            el("span", { class: "numero", texto: pt.numero }),
            el("span", { class: "chip", texto: pt.estado }),
            el("span", { class: "chip", texto: pt.tipo_trabalho }),
          ]),
          el("div", { class: "descricao", texto: pt.descricao }),
        ])
      );
    }
  } catch (erro) {
    secao.append(aviso(erro.message, "erro", "Não foi possível listar"));
  }
  return secao;
}

function campoDoFormulario(campo, valor, aoMudar) {
  const comum = { name: campo.chave, id: `campo-${campo.chave}` };
  let entrada;

  if (campo.tipo === "selecao") {
    entrada = el("select", comum, [
      el("option", { value: "", texto: "—" }),
      ...(campo.opcoes || []).map((o) =>
        el("option", { value: o, texto: o, selected: o === valor || null })
      ),
    ]);
  } else if (campo.tipo === "booleano") {
    entrada = el("input", { ...comum, type: "checkbox", checked: valor === true || null });
  } else if (campo.tipo === "numero") {
    entrada = el("input", { ...comum, type: "number", step: "any", value: valor ?? "" });
  } else if (campo.tipo === "data") {
    entrada = el("input", { ...comum, type: "date", value: valor ?? "" });
  } else {
    entrada = el("input", { ...comum, type: "text", value: valor ?? "" });
  }

  entrada.addEventListener("change", () => {
    aoMudar(
      campo.chave,
      campo.tipo === "booleano"
        ? entrada.checked
        : campo.tipo === "numero"
          ? (entrada.value === "" ? null : Number(entrada.value))
          : entrada.value
    );
  });

  return el("label", { for: comum.id }, [
    el("span", {
      class: "rotulo",
      texto: campo.obrigatorio ? `${campo.rotulo} *` : campo.rotulo,
    }),
    entrada,
  ]);
}

async function telaNova() {
  const secao = el("section");
  const bloco = el("section", { class: "painel" }, [el("h2", { texto: "Emitir PT" })]);
  const destino = el("div");
  const respostas = {};

  let areas;
  let modelos;
  try {
    [areas, modelos] = await Promise.all([api("/areas"), api("/pts/modelos")]);
  } catch (erro) {
    return aviso(erro.message, "erro", "Não foi possível carregar a tela");
  }
  if (!areas.length || !modelos.length) {
    return aviso(
      "Falta cadastro para emitir: " +
        (!areas.length ? "nenhuma área no seu escopo. " : "") +
        (!modelos.length ? "nenhum modelo de PT ativo. " : "") +
        "Isso é cadastro da unidade, não se cria por aqui.",
      "",
      "Sem onde emitir"
    );
  }

  const area = el("select", { name: "area" },
    areas.map((a) => el("option", { value: a.id, texto: `${a.codigo} — ${a.nome}` }))
  );
  // O seletor sai dos modelos existentes, e não da lista de tipos: tipo sem modelo é um beco.
  const tipo = el("select", { name: "tipo_trabalho" },
    modelos.map((m) => el("option", { value: m.tipo_trabalho, texto: m.tipo_trabalho }))
  );
  const descricao = el("textarea", { name: "descricao" });
  const de = el("input", { type: "datetime-local", name: "valida_de" });
  const ate = el("input", { type: "datetime-local", name: "valida_ate" });
  const campos = el("div");

  // O formulário vem do modelo, não da tela: trocar o tipo troca as perguntas, e as respostas
  // anteriores deixam de valer.
  function montarFormulario() {
    const modelo = modelos.find((m) => m.tipo_trabalho === tipo.value);
    campos.replaceChildren();
    for (const chave of Object.keys(respostas)) delete respostas[chave];
    for (const campo of modelo.campos) {
      campos.append(
        campoDoFormulario(campo, undefined, (chave, valor) => {
          respostas[chave] = valor;
        })
      );
    }
  }
  tipo.addEventListener("change", montarFormulario);
  montarFormulario();

  bloco.append(
    el("label", {}, [el("span", { class: "rotulo", texto: "Tipo de trabalho *" }), tipo]),
    el("label", {}, [el("span", { class: "rotulo", texto: "Área *" }), area]),
    el("label", {}, [el("span", { class: "rotulo", texto: "Descrição do serviço *" }), descricao]),
    el("label", {}, [el("span", { class: "rotulo", texto: "Válida de *" }), de]),
    el("label", {}, [el("span", { class: "rotulo", texto: "Válida até *" }), ate]),
    campos,
    destino,
    el("div", { class: "acoes" }, [
      el("button", {
        texto: "Emitir",
        onclick: async () => {
          if (!de.value || !ate.value || !descricao.value.trim()) {
            destino.replaceChildren(
              aviso("Descrição e janela de validade são obrigatórias.", "erro", "Faltam campos")
            );
            return;
          }
          // A unidade sai da área escolhida, e não do usuário: um admin não tem lotação, e a
          // área é quem sabe a que unidade o trabalho pertence.
          const escolhida = areas.find((a) => String(a.id) === area.value);
          const modelo = modelos.find((m) => m.tipo_trabalho === tipo.value);
          try {
            const pt = await api("/pts", {
              method: "POST",
              body: JSON.stringify({
                unidade_id: escolhida.unidade_id,
                area_id: escolhida.id,
                tipo_trabalho: tipo.value,
                modelo_pt_id: modelo.id,
                descricao: descricao.value,
                valida_de: instanteUtc(de.value),
                valida_ate: instanteUtc(ate.value),
                respostas,
              }),
            });
            location.hash = `#/pt/${pt.id}`;
            rotear();
          } catch (erro) {
            destino.replaceChildren(aviso(erro.message, "erro", "Emissão recusada"));
          }
        },
      }),
    ])
  );

  secao.append(
    bloco,
    // O rascunho por IA mora aqui, e não numa tela própria, porque é a mesma emissão: mesma
    // área, mesma janela e o mesmo formulário preenchido a bordo. O que muda é quem escreve o
    // texto. Uma segunda tela seria este formulário inteiro copiado, livre para divergir dele.
    blocoDeRascunhoPorIA({ areas, area, de, ate, respostas }),
    // Emitir não vai para a fila offline, ao contrário de corrigir rascunho: o número da PT é
    // do servidor, e sair da tela com uma PT que ainda não existe é pior que não emitir.
    el("p", { class: "vazio", texto: "A emissão exige conexão." })
  );
  return secao;
}

/** Descreve o serviço em texto livre e a IA propõe o rascunho.
 *
 * A divisão de trabalho é a do L10 e está escrita na tela: a IA escreve tipo, descrição,
 * perigos e controles; a janela de validade e as respostas do formulário são de quem vai a
 * bordo, e o modelo nunca as vê. Por isso este bloco reaproveita os campos já preenchidos
 * acima em vez de perguntar de novo.
 */
function blocoDeRascunhoPorIA({ areas, area, de, ate, respostas }) {
  const descricaoLivre = el("textarea", {
    name: "descricao_livre",
    rows: "3",
    placeholder: "Preciso soldar um suporte de tubulação que trincou na área do compressor.",
  });
  const destino = el("div", { class: "resultado" });
  const botao = el("button", { texto: "Propor rascunho" });

  botao.addEventListener("click", async () => {
    if (descricaoLivre.value.trim().length < 10) {
      destino.replaceChildren(
        aviso("Descreva o serviço em pelo menos uma frase.", "erro", "Descrição curta demais")
      );
      return;
    }
    if (!de.value || !ate.value) {
      destino.replaceChildren(
        aviso(
          "A janela de validade é sua, não da IA — preencha 'válida de' e 'válida até' acima.",
          "erro",
          "Falta a janela"
        )
      );
      return;
    }
    const escolhida = areas.find((a) => String(a.id) === area.value);
    botao.disabled = true;
    destino.replaceChildren(
      el("p", { class: "vazio", texto: "Lendo PTs parecidas e redigindo… pode levar minutos." })
    );
    try {
      const resultado = await api("/ai/rascunho", {
        method: "POST",
        body: JSON.stringify({
          descricao_livre: descricaoLivre.value,
          unidade_id: escolhida.unidade_id,
          area_id: escolhida.id,
          valida_de: instanteUtc(de.value),
          valida_ate: instanteUtc(ate.value),
          respostas,
        }),
      });
      // Sem ir direto para a PT: a justificativa diz em que a proposta se baseou e o que ficou
      // faltando, e é escrita para quem vai revisar. Trocar de tela a jogaria fora.
      destino.replaceChildren(
        aviso(`${resultado.pt.numero} criada em rascunho.`, "ok", "Proposta pronta para revisão"),
        el("div", { class: "resposta", texto: resultado.justificativa }),
        resultado.fontes.length
          ? el("div", { class: "fontes" }, [
              el("span", { class: "rotulo", texto: "Baseado em" }),
              ...resultado.fontes.map((numero) =>
                el("a", { class: "chip", href: `#/pts?numero=${numero}`, texto: numero })
              ),
            ])
          : el("p", { class: "vazio", texto: "Nenhuma PT parecida no acervo — texto escrito do zero." }),
        el("div", { class: "acoes" }, [
          el("a", { class: "chip", href: `#/pt/${resultado.pt.id}`, texto: "Abrir a PT →" }),
        ])
      );
    } catch (erro) {
      destino.replaceChildren(aviso(erro.message, "erro", "A proposta foi recusada"));
    } finally {
      botao.disabled = false;
    }
  });

  return el("details", { class: "painel" }, [
    el("summary", { texto: "Ou descreva o serviço e deixe a IA propor" }),
    nota("a IA", "Escreve tipo de trabalho, descrição do serviço, perigos e controles."),
    nota("você", "A janela de validade e as respostas do formulário, preenchidas acima."),
    nota("nunca vê", "As respostas do formulário — medição não sai de modelo de linguagem."),
    nota("rascunho", "Nasce pelo caminho de qualquer PT, com o mesmo fluxo pela frente."),
    // O tipo é escolhido pela IA, então o formulário preenchido acima pode não ser o do tipo
    // que ela escolher. Dizer isso antes é melhor do que deixar a recusa parecer defeito.
    nota("tipo", "Escolhido pela IA. Se o formulário for de outro tipo, nada é criado e a recusa diz quais campos faltam."),
    el("label", {}, [
      el("span", { class: "rotulo", texto: "Descrição do serviço, em texto livre" }),
      descricaoLivre,
    ]),
    el("div", { class: "acoes" }, [botao]),
    destino,
  ]);
}

/* --- IA ---------------------------------------------------------------------------------- */

/** Rótulo curto e uma frase. Não é `linha()`: aquele é `dt`/`dd` para valor de dado, em fonte
 * monoespaçada e alinhado à direita — com uma frase inteira vira uma coluna estreita ilegível.
 */
function nota(rotulo, texto) {
  return el("div", { class: "pendencia" }, [
    el("span", { class: "chip", texto: rotulo }),
    el("span", { texto }),
  ]);
}

/** O que a IA entregou, com a origem em primeiro plano.
 *
 * `fontes` são as PTs que as ferramentas leram no banco, e não as que o texto menciona. Por
 * isso a lista vazia é mostrada como estado próprio, e não escondida: quando ela está vazia o
 * servidor já trocou a resposta do modelo por "não encontrei", e a tela precisa dizer que ali
 * não há nada em que se apoiar — não que a IA falhou.
 */
function blocoDaResposta(resultado) {
  const temFonte = resultado.fontes.length > 0;
  return el("div", {}, [
    el("span", {
      class: `chip ${temFonte ? "integra" : "atencao"}`,
      texto: temFonte
        ? `${resultado.fontes.length} ${resultado.fontes.length === 1 ? "PT" : "PTs"} de origem`
        : "sem PT de origem — nada a citar",
    }),
    el("div", { class: "resposta", texto: resultado.resposta }),
    temFonte
      ? el("div", { class: "fontes" }, [
          el("span", { class: "rotulo", texto: "Baseado em" }),
          // O número é o que a pessoa reconhece; o link leva à PT pela lista, que já aplica o
          // escopo. Citação que não dá para abrir e conferir é citação pela metade.
          ...resultado.fontes.map((numero) =>
            el("a", { class: "chip", href: `#/pts?numero=${numero}`, texto: numero })
          ),
        ])
      : null,
    el("p", {
      class: "vazio",
      texto:
        `${resultado.iteracoes} ${resultado.iteracoes === 1 ? "consulta" : "consultas"} ao ` +
        `acervo · ${resultado.tokens_entrada + resultado.tokens_saida} tokens`,
    }),
  ]);
}

async function telaIA() {
  const secao = el("section");
  const pergunta = el("textarea", {
    name: "pergunta",
    rows: "3",
    placeholder: "Quais PTs de trabalho a quente estão abertas no convés?",
  });
  const destino = el("div", { class: "resultado" });
  const botao = el("button", { texto: "Perguntar" });

  botao.addEventListener("click", async () => {
    const texto = pergunta.value.trim();
    if (texto.length < 3) {
      destino.replaceChildren(aviso("Escreva a pergunta.", "erro", "Faltou a pergunta"));
      return;
    }
    botao.disabled = true;
    // Uma pergunta vira várias idas ao modelo, e com um modelo local a bordo isso passa de um
    // minuto. Uma tela parada sem explicação faz a pessoa clicar de novo — e cada clique é
    // outra consulta inteira.
    destino.replaceChildren(
      el("p", { class: "vazio", texto: "Consultando as PTs do seu acesso… pode levar um minuto." })
    );
    try {
      const resultado = await api("/ai/consulta", {
        method: "POST",
        body: JSON.stringify({ pergunta: texto }),
      });
      destino.replaceChildren(blocoDaResposta(resultado));
    } catch (erro) {
      destino.replaceChildren(aviso(erro.message, "erro", "A consulta não foi respondida"));
    } finally {
      botao.disabled = false;
    }
  });

  secao.append(
    el("section", { class: "painel" }, [
      el("h2", { texto: "Perguntar sobre as PTs" }),
      el("label", {}, [
        el("span", { class: "rotulo", texto: "Pergunta" }),
        pergunta,
      ]),
      el("div", { class: "acoes" }, [botao]),
      destino,
    ]),
    // O que esta tela é e o que ela não é, escrito onde alguém a usa pela primeira vez. Não é
    // recado de rodapé: é o contrato do produto, e é o que separa isto de um chat sobre
    // segurança do trabalho.
    el("section", { class: "painel" }, [
      el("h2", { texto: "O que a IA faz aqui" }),
      nota("lê", "Não aprova, não libera e não encerra PT — isso é de gente, na tela da PT."),
      nota("escopo", "Ela alcança exatamente as PTs que você já alcança, e nada além."),
      nota("origem", "Resposta que não se apoie numa PT do acervo não é entregue."),
      nota("números", "Prazo, validade e veredito são calculados pelo sistema, não redigidos."),
      el("p", { class: "vazio", texto: "Perguntar exige conexão." }),
    ])
  );
  return secao;
}

async function telaDetalhe(id) {
  const secao = el("section");

  let pt;
  try {
    pt = await api(`/pts/${id}`);
  } catch (erro) {
    return aviso(erro.message, "erro", "Não foi possível abrir a PT");
  }

  if (pt.__doCache) {
    secao.append(aviso("Sem conexão: esta PT é a última cópia recebida.", "", "Dado local"));
  }

  const naFila = Fila.minhas().filter((i) => i.caminho === `/pts/${pt.id}`);
  for (const item of naFila) {
    secao.append(
      item.conflito
        ? el("div", { class: "aviso erro" }, [
            el("div", { class: "titulo", texto: "Correção não aplicada" }),
            el("div", { texto: item.conflito }),
            el("div", { class: "acoes" }, [
              el("button", {
                class: "secundario",
                texto: "Descartar minha correção",
                onclick: () => {
                  Fila.remover(item.id);
                  rotear();
                },
              }),
            ]),
          ])
        : aviso(
            `Correção feita em ${instante(item.enfileirado_em)}, aguardando conexão.`,
            "",
            "Na fila"
          )
    );
  }

  secao.append(
    el("section", { class: "painel" }, [
      el("h2", { texto: pt.numero }),
      el("dl", {}, [
        linha("Estado", pt.estado),
        linha("Tipo", pt.tipo_trabalho),
        linha("Versão", pt.versao),
        linha("Válida de", instante(pt.valida_de)),
        linha("Válida até", instante(pt.valida_ate)),
        linha("Atualizada em", instante(pt.atualizado_em)),
      ]),
    ])
  );

  // --- pendências (o veredito do motor de regras) ---
  try {
    // O endpoint devolve a avaliação inteira (`AvaliacaoRead`), não a lista solta: iterar a
    // resposta direto estoura e o veredito do motor nunca chega à tela.
    const { pendencias } = await api(`/pts/${pt.id}/pendencias`);
    const bloco = el("section", { class: "painel" }, [el("h2", { texto: "Pendências" })]);
    if (!pendencias.length) {
      bloco.append(el("p", { class: "vazio", texto: "Nada pendente." }));
    }
    for (const p of pendencias) {
      bloco.append(
        el("div", { class: "pendencia" }, [
          el("span", { class: `chip ${p.severidade}`, texto: p.severidade }),
          el("span", { texto: p.mensagem }),
        ])
      );
    }
    secao.append(bloco);
  } catch (erro) {
    secao.append(aviso(erro.message, "", "Pendências indisponíveis"));
  }

  // --- anexos ---
  secao.append(await blocoDeAnexos(pt));

  // --- edição do rascunho ---
  if (pt.estado === "RASCUNHO") {
    secao.append(await blocoDeEdicao(pt));
  }

  // --- transições: exigem rede ---
  secao.append(await blocoDeTransicoes(pt));

  // --- trilha: o histórico, fechado até alguém pedir ---
  secao.append(blocoDaTrilha(pt));
  return secao;
}

/** A trilha da PT: o veredito da cadeia e cada elo, na ordem em que foram selados.
 *
 * Vive num `<details>` fechado e só busca quando alguém abre. Duas razões: é histórico, não é
 * o que se lê para decidir agora, e a trilha de uma PT antiga é a resposta mais longa que esta
 * tela pede — carregá-la em toda abertura de PT sairia caro no enlace de bordo.
 *
 * O veredito de integridade vem escrito, não só colorido: quem lê no sol do convés precisa da
 * palavra. E o que a cadeia não fecha aparece como erro, com o elo e o motivo — uma trilha que
 * não diz onde quebrou não serve para a investigação que a pede.
 */
function blocoDaTrilha(pt) {
  const bloco = el("details", { class: "painel" }, [
    el("summary", { texto: "Trilha de auditoria" }),
  ]);
  const destino = el("div");
  bloco.append(destino);

  // O `toggle` dispara também ao fechar, daí a guarda do `open`. `carregada` só é marcada no
  // sucesso: a trilha é append-only, então o que já está na tela continua valendo, mas uma
  // falha de rede tem de poder ser tentada de novo fechando e reabrindo.
  let carregada = false;
  bloco.addEventListener("toggle", async () => {
    if (!bloco.open || carregada) return;
    destino.replaceChildren(el("p", { class: "vazio", texto: "Carregando…" }));

    try {
      const trilha = await api(`/pts/${pt.id}/trilha`);
      const partes = [
        trilha.__doCache
          ? aviso("Cópia local: elos selados depois disto podem não estar aqui.", "", "Dado local")
          : null,
        trilha.integra
          ? el("span", {
              class: "chip integra",
              texto: `cadeia íntegra · ${trilha.eventos.length} elos`,
            })
          : aviso(
              trilha.quebras
                .map((q) => `elo ${q.posicao} (evento ${q.evento_id}): ${q.motivo}`)
                .join(" · "),
              "erro",
              "Cadeia quebrada"
            ),
        ...trilha.eventos.map((evento) =>
          el("div", { class: "evento" }, [
            el("div", { class: "cabeca" }, [
              el("span", { class: "momento", texto: instante(evento.ocorrido_em) }),
              // O tipo vai cru, como o servidor o gravou. O catálogo de tipos é aberto por
              // desenho — traduzi-lo aqui criaria uma segunda cópia dele, livre para divergir,
              // e um evento novo apareceria em branco na tela em vez de aparecer pelo nome.
              el("span", { class: "chip", texto: evento.tipo_evento }),
              evento.estado_destino
                ? el("span", { texto: `${evento.estado_origem || "—"} → ${evento.estado_destino}` })
                : null,
              el("span", { class: "momento", texto: evento.perfil_ator || "sistema" }),
              evento.evento_compensado_id
                ? el("span", {
                    class: "chip atencao",
                    texto: `corrige o evento ${evento.evento_compensado_id}`,
                  })
                : null,
            ]),
            evento.motivo ? el("div", { class: "motivo", texto: evento.motivo }) : null,
            // Os doze primeiros caracteres de cada ponta bastam para acompanhar o encadeamento
            // na tela: o elo seguinte abre com o que este fechou. A conferência de verdade é do
            // servidor, e é ela que o veredito acima está reportando.
            el("div", {
              class: "elo",
              texto: `${(evento.hash_anterior || "início").slice(0, 12)} → ${evento.hash_evento.slice(0, 12)}`,
            }),
          ])
        ),
      ];
      destino.replaceChildren(...partes.filter(Boolean));
      carregada = true;
    } catch (erro) {
      destino.replaceChildren(aviso(erro.message, "erro", "Trilha indisponível"));
    }
  });

  return bloco;
}

/** Baixa um anexo e entrega ao navegador.
 *
 * Não dá para usar um `<a href>` simples: a rota exige o `Authorization`, e um link não leva
 * cabeçalho. Daí o `fetch` com o token e um `blob` local.
 *
 * O link entra no documento antes do clique e a URL temporária só é revogada depois: âncora
 * solta e revogação imediata funcionam no Chrome e falham calado em outros navegadores — o
 * arquivo simplesmente não desce, sem erro nenhum na tela. Revogar importa: sem isso o blob
 * fica retido até a aba fechar, e um tablet de convés fica aberto o turno inteiro.
 */
async function baixarAnexo(pt, anexo) {
  const resposta = await fetch(`/pts/${pt.id}/anexos/${anexo.id}/conteudo`, {
    headers: { Authorization: `Bearer ${API.token}` },
  });
  if (!resposta.ok) throw new ErroDaApi(resposta.status, await resposta.json().catch(() => null));

  const url = URL.createObjectURL(await resposta.blob());
  const link = el("a", { href: url, download: anexo.nome_arquivo });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

async function blocoDeAnexos(pt) {
  const bloco = el("section", { class: "painel" }, [el("h2", { texto: "Anexos" })]);
  const destino = el("div");

  let anexos;
  try {
    anexos = await api(`/pts/${pt.id}/anexos`);
  } catch (erro) {
    bloco.append(aviso(erro.message, "", "Anexos indisponíveis"));
    return bloco;
  }

  if (!anexos.length) {
    bloco.append(el("p", { class: "vazio", texto: "Nenhum anexo." }));
  }
  for (const anexo of anexos) {
    bloco.append(
      el("div", { class: "anexo" }, [
        el("span", { class: "chip", texto: anexo.tipo }),
        el("span", { texto: anexo.nome_arquivo }),
        el("button", {
          class: "secundario",
          texto: "Baixar",
          onclick: async () => {
            try {
              await baixarAnexo(pt, anexo);
            } catch (erro) {
              destino.replaceChildren(aviso(erro.message, "erro", "Download recusado"));
            }
          },
        }),
        // Só no rascunho, e o servidor confere de novo: depois que a PT circulou, o anexo faz
        // parte do que as pessoas analisaram e assinaram.
        pt.estado !== "RASCUNHO" ? null : el("button", {
          class: "secundario",
          texto: "Remover",
          onclick: async () => {
            try {
              await api(`/pts/${pt.id}/anexos/${anexo.id}`, { method: "DELETE" });
              rotear();
            } catch (erro) {
              destino.replaceChildren(aviso(erro.message, "erro", "Remoção recusada"));
            }
          },
        }),
      ])
    );
  }

  const arquivo = el("input", { type: "file", name: "arquivo", accept: ".pdf,.jpg,.jpeg,.png" });
  const tipo = el("select", { name: "tipo" },
    TIPOS_ANEXO.map((t) => el("option", { value: t, texto: t }))
  );
  const validade = el("input", { type: "date", name: "valido_ate" });

  bloco.append(
    el("label", {}, [el("span", { class: "rotulo", texto: "Arquivo" }), arquivo]),
    el("label", {}, [el("span", { class: "rotulo", texto: "Tipo" }), tipo]),
    el("label", {}, [el("span", { class: "rotulo", texto: "Válido até (opcional)" }), validade]),
    destino,
    el("div", { class: "acoes" }, [
      el("button", {
        texto: "Anexar",
        onclick: async () => {
          if (!arquivo.files.length) {
            destino.replaceChildren(aviso("Escolha um arquivo.", "erro", "Nada para anexar"));
            return;
          }
          // O servidor decide o que entra: extensão permitida, bytes que confiram com ela e
          // tamanho. O `accept` acima é conveniência de tela, nunca a conferência.
          const corpo = new FormData();
          corpo.append("arquivo", arquivo.files[0]);
          corpo.append("tipo", tipo.value);
          if (validade.value) corpo.append("valido_ate", validade.value);
          try {
            await api(`/pts/${pt.id}/anexos`, { method: "POST", body: corpo });
            rotear();
          } catch (erro) {
            destino.replaceChildren(aviso(erro.message, "erro", "Anexo recusado"));
          }
        },
      }),
    ])
  );
  return bloco;
}

async function blocoDeEdicao(pt) {
  const bloco = el("section", { class: "painel" }, [el("h2", { texto: "Corrigir rascunho" })]);
  const respostas = { ...pt.respostas };
  const destino = el("div");

  const descricao = el("textarea", { name: "descricao", texto: pt.descricao });
  bloco.append(
    el("label", {}, [el("span", { class: "rotulo", texto: "Descrição do serviço" }), descricao])
  );

  try {
    const modelo = await api(`/pts/modelos/${pt.tipo_trabalho}`);
    for (const campo of modelo.campos) {
      bloco.append(
        campoDoFormulario(campo, respostas[campo.chave], (chave, valor) => {
          respostas[chave] = valor;
        })
      );
    }
  } catch (erro) {
    bloco.append(aviso(erro.message, "", "Formulário indisponível"));
  }

  bloco.append(
    destino,
    el("div", { class: "acoes" }, [
      el("button", {
        texto: "Salvar correção",
        onclick: async () => {
          const corpo = {
            tipo_trabalho: pt.tipo_trabalho,
            modelo_pt_id: pt.modelo_pt_id,
            area_id: pt.area_id,
            equipamento_id: pt.equipamento_id,
            descricao: descricao.value,
            valida_de: pt.valida_de,
            valida_ate: pt.valida_ate,
            perigos: pt.perigos,
            controles: pt.controles,
            respostas,
            // O que a correção viu. É o que o servidor usa para recusar um envio atrasado em
            // vez de deixá-lo apagar a alteração de outra pessoa.
            visto_em: pt.atualizado_em,
          };
          const caminho = `/pts/${pt.id}`;

          if (!navigator.onLine) {
            Fila.enfileirar({ caminho, metodo: "PATCH", corpo });
            destino.replaceChildren(
              aviso("Sem conexão: a correção sai quando o sinal voltar.", "", "Na fila")
            );
            return;
          }
          try {
            await api(caminho, { method: "PATCH", body: JSON.stringify(corpo) });
            location.hash = `#/pt/${pt.id}`;
            rotear();
          } catch (erro) {
            if (erro.status === 0 || erro.status === undefined) {
              Fila.enfileirar({ caminho, metodo: "PATCH", corpo });
              destino.replaceChildren(aviso("Enviaremos quando houver sinal.", "", "Na fila"));
            } else {
              destino.replaceChildren(aviso(erro.message, "erro", "Correção recusada"));
            }
          }
        },
      }),
    ])
  );
  return bloco;
}

async function blocoDeTransicoes(pt) {
  const bloco = el("section", { class: "painel" }, [el("h2", { texto: "Fluxo" })]);
  const destino = el("div");

  if (!navigator.onLine) {
    bloco.append(
      aviso(
        "Assinar uma etapa exige conexão: o motor de regras decide no instante da transição, " +
          "e ninguém deve sair desta tela achando que autorizou um serviço que ainda será " +
          "avaliado.",
        "",
        "Sem conexão"
      )
    );
    return bloco;
  }

  try {
    const disponiveis = await api(`/pts/${pt.id}/transicoes`);
    if (!disponiveis.length) {
      bloco.append(el("p", { class: "vazio", texto: "Nenhuma etapa disponível para você." }));
    }
    const acoes = el("div", { class: "acoes" });
    for (const transicao of disponiveis) {
      acoes.append(
        el("button", {
          class: "secundario",
          texto: transicao.destino,
          // Etapa que o perfil não assina aparece desabilitada em vez de sumir: quem está a
          // bordo precisa ver que a etapa existe e é de outra pessoa. O papel vai no rótulo
          // acessível, não só num `title` — que não aparece em toque nenhum.
          disabled: transicao.permitida ? null : "",
          "aria-label": transicao.permitida
            ? null
            : `${transicao.destino} — etapa de ${transicao.papel}`,
          onclick: async () => {
            destino.replaceChildren();
            try {
              await api(`/pts/${pt.id}/transicoes`, {
                method: "POST",
                body: JSON.stringify({
                  destino: transicao.destino,
                  // O que esta tela mostrou. Se a PT mudou depois que ela carregou, o
                  // servidor recusa — assinar é declarar que se leu o documento.
                  visto_em: pt.atualizado_em,
                }),
              });
              rotear();
            } catch (erro) {
              destino.replaceChildren(aviso(erro.message, "erro", "Transição recusada"));
            }
          },
        })
      );
    }
    bloco.append(acoes, destino);
  } catch (erro) {
    bloco.append(aviso(erro.message, "", "Fluxo indisponível"));
  }
  return bloco;
}

async function telaPainel() {
  const secao = el("section");

  try {
    const indicadores = await api("/indicadores");
    if (indicadores.__doCache) {
      secao.append(aviso("Sem conexão: números da última cópia recebida.", "", "Dado local"));
    }
    const grade = el("div", { class: "grade" }, [
      metrica("Total de PTs", indicadores.total_de_pts),
      metrica("Em execução", indicadores.em_execucao),
      metrica("Janelas fechando", indicadores.janelas_fechando, "alerta"),
      metrica("Vencidas em execução", indicadores.vencidas_em_execucao, "grave"),
      metrica("Alertas abertos", indicadores.alertas_abertos, "alerta"),
    ]);
    secao.append(el("section", { class: "painel" }, [el("h2", { texto: "Operação" }), grade]));
  } catch (erro) {
    secao.append(aviso(erro.message, "erro", "Indicadores indisponíveis"));
  }

  try {
    const alertas = await api("/alertas");
    const bloco = el("section", { class: "painel" }, [el("h2", { texto: "Alertas" })]);
    if (!alertas.length) {
      bloco.append(el("p", { class: "vazio", texto: "Nenhum alerta aberto." }));
    }
    for (const alerta of alertas) {
      const nivel = Math.min(alerta.nivel_escalonamento, 2);
      bloco.append(
        el("div", { class: `cartao nivel-${nivel}` }, [
          el("div", { class: "cabeca" }, [
            // O nível vai escrito, não só colorido: no sol do convés a cor some, e nem todo
            // mundo distingue âmbar de vermelho.
            el("span", {
              class: `chip ${nivel === 2 ? "bloqueante" : nivel === 1 ? "atencao" : ""}`,
              texto: `nível ${alerta.nivel_escalonamento}`,
            }),
            el("span", { class: "chip", texto: alerta.tipo }),
            el("span", { class: "chip", texto: `resp. ${alerta.responsavel}` }),
            el("span", { class: "chip", texto: alerta.status }),
          ]),
          el("div", { class: "descricao", texto: alerta.mensagem }),
        ])
      );
    }
    secao.append(bloco);
  } catch (erro) {
    secao.append(aviso(erro.message, "erro", "Alertas indisponíveis"));
  }
  return secao;
}

function metrica(rotulo, valor, tipo = "") {
  return el("div", { class: `metrica ${tipo}` }, [
    el("div", { class: "valor", texto: String(valor ?? "—") }),
    el("div", { class: "rotulo", texto: rotulo }),
  ]);
}

/* --- roteamento ------------------------------------------------------------------------ */

function sair() {
  API.token = null;
  API.matricula = null;
  API.usuario = null;
  localStorage.removeItem("aegis_token");
  localStorage.removeItem("aegis_matricula");
  // A cópia local de dados autenticados sai junto. A fila fica: é trabalho ainda não enviado,
  // está marcada com o dono e só sai quando ele voltar.
  limparCacheDeDados();
  Fila.pintar();
  location.hash = "#/login";
}

async function rotear() {
  const bruto = location.hash.slice(2) || (API.token ? "pts" : "login");
  const [caminho, parametros = ""] = bruto.split("?");
  const partes = caminho.split("/");

  abas.hidden = !API.token;
  for (const link of abas.querySelectorAll("a")) {
    link.classList.toggle("ativa", link.getAttribute("href") === `#/${partes[0]}`);
  }

  if (!API.token && partes[0] !== "login") {
    location.hash = "#/login";
    return;
  }

  tela.replaceChildren(el("p", { class: "vazio", texto: "Carregando…" }));
  let conteudo;
  try {
    if (partes[0] === "sair") return sair();
    if (partes[0] === "login") conteudo = telaLogin();
    else if (partes[0] === "nova") conteudo = await telaNova();
    else if (partes[0] === "ia") conteudo = await telaIA();
    else if (partes[0] === "pt") conteudo = await telaDetalhe(partes[1]);
    else if (partes[0] === "painel") conteudo = await telaPainel();
    else conteudo = await telaLista(parametros);
  } catch (erro) {
    conteudo = aviso(erro.message, "erro", "Falha inesperada");
  }
  tela.replaceChildren(conteudo);
}

window.addEventListener("hashchange", rotear);

/* --- partida --------------------------------------------------------------------------- */

pintarConexao(navigator.onLine);
Fila.pintar();
rotear();
if (navigator.onLine) Fila.enviar();

if ("serviceWorker" in navigator) {
  // Servido da raiz por uma rota do FastAPI: em `/static/` o escopo não cobriria a aplicação.
  navigator.serviceWorker.register("/sw.js").catch((erro) => {
    console.warn("Service worker não registrado:", erro.message);
  });
}
