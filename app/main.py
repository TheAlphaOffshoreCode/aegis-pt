"""Ponto de entrada da API do AEGIS PT."""

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import logging

from app.config import get_settings
from app.routers import ai, auth, health, indicadores, pts
from app.rules.pendencias import ConflitoDeNegocio
from app.security.cabecalhos import CabecalhosDeSeguranca

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
    """
    registro.exception("Falha não tratada em %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erro interno. A ocorrência foi registrada."},
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

# Montado em /static, e não em "/", para que nenhum router incluído depois seja engolido.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Entrega o shell do PWA."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    """O service worker precisa ser servido da raiz.

    O escopo de um service worker é a pasta de onde ele veio: em `/static/sw.js` ele só
    controlaria `/static/`, e não a aplicação. Servi-lo aqui dá a ele o escopo `/` sem
    depender de cabeçalho `Service-Worker-Allowed`.
    """
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        # Sem isto o navegador pode servir um worker velho do próprio cache HTTP e a
        # atualização do aplicativo nunca chega ao tablet.
        headers={"Cache-Control": "no-cache"},
    )
