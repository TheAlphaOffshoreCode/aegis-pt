"""Configuração da aplicação, lida exclusivamente de variáveis de ambiente."""

from functools import lru_cache
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

    # Origens do PWA. Em produção, listar explicitamente; nunca "*".
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]


@lru_cache
def get_settings() -> Settings:
    """Instância única de Settings, resolvida na primeira chamada."""
    return Settings()
