"""Configuração da aplicação, lida exclusivamente de variáveis de ambiente."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# `static/` é servido como está, sem autorização nenhuma. Anexo gravado ali vira documento
# público — inclusive a APR e o relatório de incidente.
PASTA_PUBLICA = (Path(__file__).resolve().parent.parent / "static").resolve()


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

    # Chave da Claude API. Sem default e lida só aqui, no backend (regra 7): a aplicação sobe
    # sem ela, e apenas as rotas de IA respondem 503.
    anthropic_api_key: str | None = None
    ai_modelo: str = "claude-opus-5"
    # Preenchido, manda a IA para um modelo local (Ollama) e a chave deixa de ser usada — é
    # o modo de bordo: sem enlace, sem custo por token e sem PT saindo da unidade. Quem troca
    # a URL troca também `ai_modelo`, que passa a ser o nome do modelo local (`gemma4:latest`).
    ai_base_url: str | None = None
    # A janela do Ollama é bem menor que a do modelo por padrão, e o que passa dela é cortado
    # **em silêncio, pela frente** — onde está o system com as regras invioláveis.
    ai_local_contexto: int = 16384
    # Um modelo local em CPU responde em dezenas de segundos. O padrão do httpx é 5 s, o que
    # transformaria lentidão esperada em falha inventada.
    ai_local_timeout: int = 300
    # Camadas a mandar para a GPU. `None` deixa o Ollama decidir, que é o certo num servidor
    # com uma placa que caiba o modelo. Numa máquina com duas GPUs pequenas a divisão
    # automática estoura `GGML_ASSERT(n_inputs < GGML_SCHED_MAX_SPLIT_INPUTS)` e derruba o
    # runner — ali é preciso fixar (0 força só CPU). Botão de calibração, não configuração
    # especulativa: existe porque a máquina de desenvolvimento quebrou sem ele.
    ai_local_num_gpu: int | None = None
    # Raciocínio do modelo local. Ligado porque **é o que faz ele usar as ferramentas**:
    # medido no gemma4, desligado ele devolve uma pergunta de volta em 8 s (e a resposta é
    # descartada por não ter fonte); ligado, chama `buscar_pts` em 53 s. Resposta inútil e
    # rápida é pior que resposta certa e lenta. Desligar só num modelo que dispense.
    ai_local_pensar: bool = True
    # Folga de propósito: no Opus 5 o raciocínio é adaptativo e ligado por padrão, e
    # `max_tokens` limita raciocínio + resposta juntos — apertar aqui trunca no meio.
    ai_max_tokens: int = 8000
    ai_esforco: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # Teto de idas e voltas com ferramentas. Consulta que não converge em 6 passos não vai
    # convergir em 20 — e cada passo custa tokens.
    ai_max_iteracoes: int = 6

    # Origens do PWA. Em produção, listar explicitamente; nunca "*".
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]

    @field_validator("upload_dir")
    @classmethod
    def _fora_da_pasta_publica(cls, valor: Path) -> Path:
        """Recusa subir se os anexos forem gravados dentro de `static/`.

        Era só um comentário até aqui, e comentário não impede nada: bastava
        `AEGIS_UPLOAD_DIR=static/uploads` no ambiente para todo anexo virar público, sem erro
        nenhum aparecendo. Falhar na partida é o único momento em que isso ainda é barato.
        """
        resolvido = valor.expanduser().resolve()
        if resolvido == PASTA_PUBLICA or PASTA_PUBLICA in resolvido.parents:
            raise ValueError(
                f"AEGIS_UPLOAD_DIR ({resolvido}) está dentro de {PASTA_PUBLICA}, que é "
                "servida publicamente. Aponte para um diretório fora dela."
            )
        return valor


@lru_cache
def get_settings() -> Settings:
    """Instância única de Settings, resolvida na primeira chamada."""
    return Settings()
