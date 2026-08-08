"""O PWA como o navegador o vê: shell, manifesto, service worker e fontes locais.

São verificações baratas de coisas que quebram em silêncio — um caminho errado no manifesto
ou um service worker fora da raiz não derrubam teste nenhum, só fazem o aplicativo deixar de
instalar e de abrir sem sinal, que é justamente o que este loop entregou.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
