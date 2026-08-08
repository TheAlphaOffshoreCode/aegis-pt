"""Schemas do painel operacional."""

from pydantic import BaseModel


class IndicadoresRead(BaseModel):
    """Contagens no escopo de quem perguntou. Todo valor é um `COUNT`, nenhum é estimado."""

    total_de_pts: int
    pts_por_estado: dict[str, int]
    pts_por_tipo: dict[str, int]
    em_execucao: int
    janelas_fechando: int
    vencidas_em_execucao: int
    alertas_abertos: int
    alertas_por_nivel: dict[int, int]


class SincronizacaoRead(BaseModel):
    """O que a passagem de sincronização fez."""

    abertos: int
    reabertos: int
    escalonados: int
    resolvidos: int
