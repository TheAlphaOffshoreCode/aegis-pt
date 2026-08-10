"""Ponto de entrada da API do AEGIS PT."""

import hashlib
import re
from pathlib import Path

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import logging

from app.config import get_settings
from app.routers import ai, auth, health, indicadores, organizacao, pts
from app.rules.pendencias import ConflitoDeNegocio
from app.security.cabecalhos import CABECALHOS, CabecalhosDeSeguranca

registro = logging.getLogger("aegis")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Plataforma Inteligente de Gestão de Permissões de Trabalho",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Depois do CORS na lista, portanto **antes** dele na resposta: os cabeçalhos precisam sair
# também nas respostas de erro, que o CORS não chega a montar.
app.add_middleware(CabecalhosDeSeguranca, hsts=settings.environment != "development")


@app.exception_handler(Exception)
def falha_inesperada(request: Request, exc: Exception) -> JSONResponse:
    """Erro não previsto vira `500` genérico — o detalhe vai para o log, não para a resposta.

    Uma stack trace na resposta entrega caminho de arquivo, versão de biblioteca e, às vezes,
    trecho de consulta. Quem precisa dela é quem opera o serviço, não quem chamou.

    Os cabeçalhos de segurança são repetidos aqui de propósito. Este handler é executado pelo
    `ServerErrorMiddleware`, que fica **acima** de todo middleware da aplicação — o
    `CabecalhosDeSeguranca` nunca chega a ver esta resposta. Sem esta linha, a única resposta
    sem proteção do serviço inteiro seria justamente a que sai quando algo deu errado.
    """
    registro.exception("Falha não tratada em %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erro interno. A ocorrência foi registrada."},
        headers=dict(CABECALHOS),
    )


@app.exception_handler(ConflitoDeNegocio)
def conflito_de_negocio(request: Request, exc: ConflitoDeNegocio) -> JSONResponse:
    """Conflito de negócio é sempre 409 com a lista estruturada, em qualquer rota.

    Centralizado para nenhuma rota inventar o próprio formato — a tela depende de `codigo` e
    `campo` para saber onde marcar o erro.
    """
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": [pendencia.como_dict() for pendencia in exc.pendencias]},
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(pts.router)
app.include_router(ai.router)
app.include_router(indicadores.router)
app.include_router(organizacao.router)

# Montado em /static, e não em "/", para que nenhum router incluído depois seja engolido.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Entrega o shell do PWA."""
    return FileResponse(STATIC_DIR / "index.html")


def _versao_do_shell() -> str:
    """Impressão digital do conteúdo estático servido ao navegador.

    O `sw.js` sai daqui com esta versão embutida, e é ela que decide quando o navegador troca
    de worker e refaz o cache. Derivá-la do conteúdo, em vez de escrevê-la à mão, é o que
    impede o estado que já apareceu na prática: **um shell misturado** — `index.html` novo com
    `app.js` velho, uma aba que existe e uma tela que ela não sabe abrir. Cada arquivo é
    revalidado por conta própria, então nada garante que os dois cheguem juntos ao tablet a
    menos que a versão do worker mude quando qualquer um deles mudar.

    O próprio `sw.js` fica de fora do resumo: ele contém a versão, e incluí-lo faria o valor
    depender de si mesmo.
    """
    # ponytail: relê o estático a cada requisição do worker (~70 KB, quase tudo fonte). Se um
    # dia isso pesar, a chave de um cache é o par (mtime, tamanho) de cada arquivo.
    resumo = hashlib.sha256()
    for arquivo in sorted(STATIC_DIR.rglob("*")):
        if arquivo.is_file() and arquivo.name != "sw.js":
            resumo.update(arquivo.read_bytes())
    return resumo.hexdigest()[:12]


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    """O service worker precisa ser servido da raiz, e com a versão do shell embutida.

    O escopo de um service worker é a pasta de onde ele veio: em `/static/sw.js` ele só
    controlaria `/static/`, e não a aplicação. Servi-lo aqui dá a ele o escopo `/` sem
    depender de cabeçalho `Service-Worker-Allowed`.
    """
    fonte = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    corpo, trocas = re.subn(
        r'const VERSAO = "[^"]+"',
        f'const VERSAO = "aegis-{_versao_do_shell()}"',
        fonte,
        count=1,
    )
    if trocas != 1:
        # Falha alto: sem a substituição o worker serviria uma versão fixa para sempre, e a
        # atualização pararia de chegar sem nada quebrar por perto.
        raise RuntimeError("Não encontrei a declaração de VERSAO em static/sw.js")

    return Response(
        content=corpo,
        media_type="application/javascript",
        # Sem isto o navegador pode servir um worker velho do próprio cache HTTP e a
        # atualização do aplicativo nunca chega ao tablet.
        headers={"Cache-Control": "no-cache"},
    )
