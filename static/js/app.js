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
  usuario: null,
};

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
      return corpo.detail.map((p) => p.mensagem || p.codigo).join(" · ");
    }
    return corpo?.detail || `Erro ${status}`;
  }
}

async function api(caminho, opcoes = {}) {
  const cabecalhos = { ...(opcoes.headers || {}) };
  if (API.token) cabecalhos.Authorization = `Bearer ${API.token}`;
  if (opcoes.body) cabecalhos["Content-Type"] = "application/json";

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
    itens.push({ ...item, id: Date.now(), enfileirado_em: new Date().toISOString() });
    Fila.gravar(itens);
  },
  remover(id) {
    Fila.gravar(Fila.ler().filter((i) => i.id !== id));
  },
  marcarConflito(id, mensagem) {
    Fila.gravar(Fila.ler().map((i) => (i.id === id ? { ...i, conflito: mensagem } : i)));
  },
  pintar() {
    const itens = Fila.ler();
    const conflitos = itens.filter((i) => i.conflito).length;
    chipFila.hidden = itens.length === 0;
    chipFila.textContent = conflitos
      ? `${conflitos} em conflito`
      : `${itens.length} na fila`;
    chipFila.className = `chip ${conflitos ? "bloqueante" : "offline"}`;
  },

  async enviar() {
    for (const item of Fila.ler()) {
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
        API.token = dados.access_token;
        localStorage.setItem("aegis_token", API.token);
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

async function telaLista(parametros) {
  const secao = el("section");
  const filtroEstado = new URLSearchParams(parametros).get("estado") || "";

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
    ])
  );

  try {
    const busca = filtroEstado ? `?estado=${filtroEstado}` : "";
    const pagina = await api(`/pts${busca}`);
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

  const naFila = Fila.ler().filter((i) => i.caminho === `/pts/${pt.id}`);
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
    const pendencias = await api(`/pts/${pt.id}/pendencias`);
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

  // --- edição do rascunho ---
  if (pt.estado === "RASCUNHO") {
    secao.append(await blocoDeEdicao(pt));
  }

  // --- transições: exigem rede ---
  secao.append(await blocoDeTransicoes(pt));
  return secao;
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
                body: JSON.stringify({ destino: transicao.destino }),
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
  API.usuario = null;
  localStorage.removeItem("aegis_token");
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
