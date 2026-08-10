"""O PWA como o navegador o vê: shell, manifesto, service worker e fontes locais.

São verificações baratas de coisas que quebram em silêncio — um caminho errado no manifesto
ou um service worker fora da raiz não derrubam teste nenhum, só fazem o aplicativo deixar de
instalar e de abrir sem sinal, que é justamente o que este loop entregou.
"""

import json
import re
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.models.pessoa import Usuario
from app.models.tipos import agora_utc

ESTATICO = Path(__file__).resolve().parent.parent / "static"


def test_o_shell_e_servido_na_raiz(client: TestClient) -> None:
    resposta = client.get("/")

    assert resposta.status_code == 200
    assert "manifest.webmanifest" in resposta.text
    assert 'href="/static/css/aegis.css"' in resposta.text


def test_o_service_worker_vem_da_raiz(client: TestClient) -> None:
    """Em `/static/sw.js` o escopo seria `/static/` e o worker não controlaria a aplicação."""
    resposta = client.get("/sw.js")

    assert resposta.status_code == 200
    assert "javascript" in resposta.headers["content-type"]
    assert resposta.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("caminho", ["/", "/static/js/app.js", "/static/css/aegis.css", "/sw.js"])
def test_o_shell_e_sempre_revalidado(client: TestClient, caminho: str) -> None:
    """Sem `Cache-Control`, o navegador reusa pela heurística e cada arquivo vence na sua hora.

    É o segundo caminho pelo qual o shell chega misturado, e este não passa pelo service worker:
    basta o `index.html` sair do frescor antes do `app.js` para a tela ganhar uma aba que a
    aplicação carregada não sabe abrir.
    """
    resposta = client.get(caminho)

    assert resposta.headers["cache-control"] == "no-cache"
    # `no-cache` sem validador seria download completo a cada carga: é o `ETag` que faz a
    # revalidação custar um `304`.
    assert "etag" in resposta.headers or caminho == "/sw.js"


def test_a_revalidacao_tambem_carrega_a_diretiva(client: TestClient) -> None:
    """O `304` é o caminho quente — é ele que responde em toda recarga.

    Se a diretiva viesse só no `200`, a resposta que o navegador realmente recebe no dia a dia
    ficaria sem instrução nenhuma e a heurística voltaria a valer, com o mesmo desfecho de
    antes. O `Starlette` monta o `304` dentro do mesmo `file_response`, e é disso que este teste
    depende: se um dia deixar de montar, é aqui que se descobre.
    """
    primeira = client.get("/static/js/app.js")
    segunda = client.get(
        "/static/js/app.js", headers={"If-None-Match": primeira.headers["etag"]}
    )

    assert segunda.status_code == 304
    assert segunda.headers["cache-control"] == "no-cache"


def test_o_worker_sai_com_a_versao_do_shell_embutida(client: TestClient) -> None:
    """O `sw.js` em disco traz um valor de espera; quem serve troca pela impressão digital.

    Se a substituição deixar de acontecer, o worker passa a anunciar sempre a mesma versão, o
    navegador nunca o vê mudar, e a atualização para de chegar ao tablet sem nada quebrar por
    perto — exatamente o tipo de falha silenciosa que o cache-first cria.
    """
    corpo = client.get("/sw.js").text

    assert 'const VERSAO = "aegis-dev"' not in corpo
    assert re.search(r'const VERSAO = "aegis-[0-9a-f]{12}"', corpo)


def test_a_versao_do_shell_muda_quando_o_shell_muda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """É a garantia inteira: conteúdo diferente, versão diferente, cache refeito.

    O `sw.js` fica fora do resumo de propósito — ele carrega a versão, e incluí-lo faria o
    valor depender de si mesmo.
    """
    (tmp_path / "app.js").write_text("primeira versão", encoding="utf-8")
    (tmp_path / "sw.js").write_text("const VERSAO = 'x'", encoding="utf-8")
    monkeypatch.setattr(main, "STATIC_DIR", tmp_path)

    antes = main._versao_do_shell()
    assert main._versao_do_shell() == antes, "shell parado, versão parada"

    (tmp_path / "sw.js").write_text("const VERSAO = 'y'", encoding="utf-8")
    assert main._versao_do_shell() == antes

    # Sem limpar o cache de propósito: se a leitura estivesse presa nele, a mudança abaixo
    # passaria despercebida — que é a única forma de esta função enganar quem depende dela.
    (tmp_path / "app.js").write_text("segunda versão", encoding="utf-8")
    assert main._versao_do_shell() != antes


def test_o_manifesto_declara_o_minimo_para_instalar(client: TestClient) -> None:
    manifesto = json.loads((ESTATICO / "manifest.webmanifest").read_text(encoding="utf-8"))

    assert manifesto["start_url"] == "/"
    assert manifesto["display"] == "standalone"
    assert manifesto["background_color"] == "#0b0f14"
    # Um ícone comum e um maskable: sem o segundo, o Android recorta o desenho.
    assert {i["purpose"] for i in manifesto["icons"]} == {"any", "maskable"}


@pytest.mark.parametrize(
    "caminho",
    [
        "/static/manifest.webmanifest",
        "/static/js/app.js",
        "/static/css/aegis.css",
        "/static/icons/aegis.svg",
        "/static/icons/aegis-maskable.svg",
        "/static/fonts/oswald-600.woff2",
        "/static/fonts/jetbrains-mono-400.woff2",
    ],
)
def test_tudo_que_o_service_worker_promete_guardar_existe(
    client: TestClient, caminho: str
) -> None:
    """O `addAll` do install é tudo-ou-nada: um caminho errado e o worker nunca instala."""
    assert client.get(caminho).status_code == 200


def test_o_shell_do_service_worker_bate_com_o_disco() -> None:
    """A lista do worker e os arquivos servidos não podem divergir sem alguém notar."""
    sw = (ESTATICO / "sw.js").read_text(encoding="utf-8")
    inicio = sw.index("ARQUIVOS_DO_SHELL = [")
    listados = [
        linha.strip().strip('",')
        for linha in sw[inicio : sw.index("];", inicio)].splitlines()
        if linha.strip().startswith('"/')
    ]

    ausentes = [c for c in listados if c != "/" and not (ESTATICO.parent / c.lstrip("/")).exists()]
    assert ausentes == []


def test_as_fontes_da_identidade_sao_locais() -> None:
    """Sem CDN em produção: fonte que só carrega online some justamente offshore."""
    css = (ESTATICO / "css" / "aegis.css").read_text(encoding="utf-8")

    assert "https://" not in css
    assert css.count("@font-face") == 4
    assert (ESTATICO / "fonts" / "LICENSE.md").exists()


def test_nenhum_recurso_externo_no_shell() -> None:
    """Um `<script src>` ou `<link href>` para fora quebraria o aplicativo sem rota."""
    html = (ESTATICO / "index.html").read_text(encoding="utf-8")

    assert "http://" not in html
    assert "https://" not in html


def _rota_generica(caminho: str) -> str:
    """`/pts/${pt.id}/pendencias` e `/pts/{pt_id}/pendencias` viram a mesma coisa.

    O `${...}` sai primeiro: invertido, o `{...}` come o miolo, sobra um `$` solto, e a
    conferência passa a pular as rotas com parâmetro — que são quase todas.
    """
    generica = re.sub(r"\{[^}]*\}", "{}", re.sub(r"\$\{[^}]+\}", "{}", caminho)).split("?")[0]
    # `/pts${busca}` interpola a query, não um segmento: o `{}` no fim não é parâmetro de rota.
    return generica[:-2] if generica.endswith("{}") and not generica.endswith("/{}") else generica


def test_o_frontend_nao_itera_resposta_que_nao_e_lista(client: TestClient) -> None:
    """Cada `api()` do app.js tem de tratar a resposta com a forma que o endpoint devolve.

    `/pts/{id}/pendencias` responde a avaliação inteira (`AvaliacaoRead`) e o detalhe iterava a
    resposta direto: `.length` saía `undefined`, o `for...of` estourava no objeto e o `catch`
    virava um aviso com cara de falha de rede. O veredito do motor nunca chegou à tela, em
    nenhuma PT, e nada caiu — a suíte inteira é de backend.
    """
    listas: dict[str, bool] = {}
    for rota, operacoes in client.get("/openapi.json").json()["paths"].items():
        resposta = operacoes.get("get", {}).get("responses", {}).get("200", {})
        # Nem toda resposta é JSON — um download declara o seu próprio tipo. Sem schema aqui
        # não há forma a conferir, e a rota sai fora em vez de derrubar a conferência inteira.
        schema = resposta.get("content", {}).get("application/json", {}).get("schema")
        if schema is not None:
            listas[_rota_generica(rota)] = schema.get("type") == "array"

    js = (ESTATICO / "js" / "app.js").read_text(encoding="utf-8")
    divergentes, conferidas = [], 0
    for atribuicao in re.finditer(r"const\s+(\w+)\s*=\s*await api\([`\"]([^`\"]+)[`\"]\)", js):
        nome, caminho = atribuicao.group(1), _rota_generica(atribuicao.group(2))
        if caminho not in listas:
            continue
        conferidas += 1
        # Só o trecho logo abaixo da chamada, que é onde a resposta é consumida — o nome pode
        # se repetir mais adiante no arquivo com outro significado.
        adiante = js[atribuicao.end() : atribuicao.end() + 400]
        como_lista = f"{nome}.length" in adiante or f"of {nome})" in adiante
        if como_lista and not listas[caminho]:
            divergentes.append(f"{caminho} devolve objeto e o app.js trata `{nome}` como lista")

    assert divergentes == []
    # Sem isto a conferência se desliga em silêncio: basta o regex deixar de casar, ou uma
    # rota mudar de forma, para o laço passar batido e o teste virar verde permanente.
    assert conferidas >= 5, f"a conferência só alcançou {conferidas} chamadas — regex quebrado?"


def test_a_tela_sabe_ler_o_erro_de_validacao_da_api(
    client: TestClient,
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Um `422` tem de chegar à tela com texto, e não como caixa vermelha vazia.

    Duas listas diferentes caem no mesmo `ErroDaApi`: o `409` traz pendências do motor de regras
    (`mensagem`, `codigo`) e o `422` traz erros do Pydantic, que usam `msg`. Enquanto o `app.js`
    só conhecia as duas primeiras, todo `422` virava string vazia — e o caso é banal, basta
    emitir com a janela de validade invertida.

    O teste extrai do próprio `app.js` as chaves que ele sabe ler e confere contra o que a API
    devolve de fato. Pega os dois lados: a API mudar de formato, ou alguém encurtar a lista no
    JavaScript. O que ele **não** pega é o texto ficar ilegível na tela — para isso faltaria um
    runner de JavaScript (P48).
    """
    criar_usuario(matricula="70001")
    inicio = agora_utc()
    resposta = client.post(
        "/pts",
        headers=autenticar("70001"),
        json={
            "unidade_id": 1, "area_id": 1, "tipo_trabalho": "trabalho_a_quente",
            "modelo_pt_id": 1, "descricao": "janela invertida de propósito",
            # Fim antes do início: recusado pelo validador do schema, antes de tocar o banco.
            "valida_de": (inicio + timedelta(hours=8)).isoformat(),
            "valida_ate": inicio.isoformat(),
            "respostas": {},
        },
    )
    assert resposta.status_code == 422, resposta.text

    js = (ESTATICO / "js" / "app.js").read_text(encoding="utf-8")
    chave = re.search(r"corpo\.detail\.map\(\(p\) => ([^)]+)\)", js)
    assert chave, "não achei como o app.js lê a lista de erros"
    conhecidas = set(re.findall(r"p\.(\w+)", chave.group(1)))

    for item in resposta.json()["detail"]:
        legivel = [item[k] for k in conhecidas if item.get(k)]
        assert legivel, f"a tela não teria texto para mostrar deste item: {item}"
