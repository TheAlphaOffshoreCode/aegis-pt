"""Ponto de entrada da API do AEGIS PT."""

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import auth, health, pts
from app.rules.pendencias import ConflitoDeNegocio

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

# Montado em /static, e não em "/", para que nenhum router incluído depois seja engolido.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Entrega o shell do PWA."""
    return FileResponse(STATIC_DIR / "index.html")
