"""Configuração da aplicação, lida exclusivamente de variáveis de ambiente."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AEGIS_",
        extra="ignore",
    )

    app_name: str = "AEGIS PT"
    environment: Literal["development", "production"] = "development"

    # Sem default: a aplicação não sobe sem um segredo real definido no ambiente.
    secret_key: str = Field(min_length=32)

    database_url: str = "sqlite:///./aegis_pt.db"

    # Um turno a bordo. Fica configurável porque a operação real ajusta esse número,
    # e sessão que vence no meio do turno é o que empurra gente a compartilhar login.
    token_expiracao_minutos: int = 480

    # Onde os anexos são gravados. Em produção aponta para um volume; nunca para dentro de
    # `static/`, que é servido diretamente e transformaria upload em conteúdo público.
    upload_dir: Path = Path("uploads")
    anexo_tamanho_maximo_mb: int = 10

    # Origens do PWA. Em produção, listar explicitamente; nunca "*".
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]


@lru_cache
def get_settings() -> Settings:
    """Instância única de Settings, resolvida na primeira chamada."""
    return Settings()
