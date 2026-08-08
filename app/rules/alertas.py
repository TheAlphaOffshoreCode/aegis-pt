"""Quando um alerta existe, e para quem ele sobe.

Como o resto de `app/rules/`: funções puras, sem banco. O serviço carrega o que é preciso e
passa; aqui só se decide. É o que permite testar cada condição sozinha, com um relógio fixo,
em vez de montar meio sistema para provar que um prazo vence.

Nenhum destes prazos sai de modelo de linguagem (regra 2) — todos vêm das constantes de
`exigencias.py` e da data que o chamador informou.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from app.models.enums import EstadoPT, PerfilUsuario
from app.models.permissao import PermissaoTrabalho
from app.models.pessoa import Certificacao
from app.rules.exigencias import (
    DIAS_DE_AVISO_DE_VENCIMENTO,
    ESCADA_DE_ESCALONAMENTO,
    ESTADOS_EM_APROVACAO,
    HORAS_ATE_PT_PARADA,
    HORAS_DE_AVISO_DE_FIM_DE_JANELA,
    HORAS_POR_NIVEL_DE_ESCALONAMENTO,
)

ENTIDADE_PT = "permissao_trabalho"
ENTIDADE_CERTIFICACAO = "certificacao"


@dataclass(frozen=True)
class Condicao:
    """Um alerta que deveria existir agora. Sem `id` e sem status: isso é do banco."""

    tipo: str
    entidade: str
    entidade_id: int
    unidade_id: int
    mensagem: str
    prazo: datetime

    @property
    def chave(self) -> tuple[str, str, int]:
        """Identidade do alerta. A mesma condição detectada de novo é o mesmo alerta."""
        return (self.tipo, self.entidade, self.entidade_id)


def nivel_de_escalonamento(prazo: datetime, agora: datetime) -> int:
    """Quantos níveis o alerta já subiu, contando do prazo até agora.

    Determinístico e sem estado: o nível é função do relógio, não de quantas vezes a
    sincronização rodou. Rodar duas vezes no mesmo minuto dá o mesmo número.
    """
    if agora <= prazo:
        return 0
    vencidos = (agora - prazo) // timedelta(hours=HORAS_POR_NIVEL_DE_ESCALONAMENTO)
    return min(int(vencidos), len(ESCADA_DE_ESCALONAMENTO) - 1)


def responsavel_do_nivel(nivel: int) -> PerfilUsuario:
    """Para quem o alerta está agora. Acima do último nível não há para quem escalar."""
    return ESCADA_DE_ESCALONAMENTO[min(nivel, len(ESCADA_DE_ESCALONAMENTO) - 1)]


def condicoes_das_pts(
    pts: Sequence[PermissaoTrabalho], agora: datetime
) -> list[Condicao]:
    """Alertas que as PTs em andamento geram no instante `agora`."""
    condicoes: list[Condicao] = []
    for pt in pts:
        if pt.estado == EstadoPT.EM_EXECUCAO:
            if pt.valida_ate < agora:
                # O caso que mais importa: gente trabalhando com a autorização vencida.
                condicoes.append(
                    Condicao(
                        tipo="pt_vencida_em_execucao",
                        entidade=ENTIDADE_PT,
                        entidade_id=pt.id,
                        unidade_id=pt.unidade_id,
                        mensagem=(
                            f"{pt.numero} continua em execução com a janela encerrada em "
                            f"{pt.valida_ate:%d/%m/%Y %H:%M} UTC"
                        ),
                        prazo=pt.valida_ate,
                    )
                )
            elif pt.valida_ate <= agora + timedelta(hours=HORAS_DE_AVISO_DE_FIM_DE_JANELA):
                condicoes.append(
                    Condicao(
                        tipo="pt_vencendo",
                        entidade=ENTIDADE_PT,
                        entidade_id=pt.id,
                        unidade_id=pt.unidade_id,
                        mensagem=(
                            f"{pt.numero} encerra a janela em "
                            f"{pt.valida_ate:%d/%m/%Y %H:%M} UTC"
                        ),
                        prazo=pt.valida_ate,
                    )
                )
            continue

        if pt.estado in ESTADOS_EM_APROVACAO:
            limite = pt.atualizado_em + timedelta(hours=HORAS_ATE_PT_PARADA)
            if agora >= limite:
                condicoes.append(
                    Condicao(
                        tipo="pt_parada",
                        entidade=ENTIDADE_PT,
                        entidade_id=pt.id,
                        unidade_id=pt.unidade_id,
                        mensagem=(
                            f"{pt.numero} está em {pt.estado} desde "
                            f"{pt.atualizado_em:%d/%m/%Y %H:%M} UTC sem avançar"
                        ),
                        prazo=limite,
                    )
                )
    return condicoes


def condicoes_das_certificacoes(
    certificacoes: Sequence[Certificacao], agora: datetime
) -> list[Condicao]:
    """Habilitações vencidas ou vencendo dentro da janela de aviso.

    Os dois casos são tipos distintos, com o mesmo vocabulário que o motor do L4 já usa: uma
    habilitação vencida não é "quase vencendo", e dizer "vence em" sobre uma data passada é o
    tipo de frase que faz alguém a bordo ler errado.
    """
    hoje = agora.date()
    limite = (agora + timedelta(days=DIAS_DE_AVISO_DE_VENCIMENTO)).date()
    condicoes: list[Condicao] = []
    for certificacao in certificacoes:
        if certificacao.valida_ate > limite:
            continue
        if certificacao.usuario.unidade_id is None:
            # Sem lotação não há unidade para escopar o alerta, e um alerta que ninguém
            # enxerga é pior que nenhum. Vira pendência de cadastro, não alerta.
            continue

        vencida = certificacao.valida_ate < hoje
        condicoes.append(
            Condicao(
                tipo="certificacao_vencida" if vencida else "certificacao_a_vencer",
                # A entidade é a certificação, não a pessoa: quem tem NR-33 e NR-35 vencendo
                # tem dois problemas com datas diferentes, e chavear por usuário fundiria os
                # dois num alerta só.
                entidade=ENTIDADE_CERTIFICACAO,
                entidade_id=certificacao.id,
                unidade_id=certificacao.usuario.unidade_id,
                mensagem=(
                    f"{certificacao.tipo} de {certificacao.usuario.nome} "
                    f"{'venceu' if vencida else 'vence'} em "
                    f"{certificacao.valida_ate:%d/%m/%Y}"
                ),
                # `valida_ate` é data, não instante: o prazo é o fim daquele dia em UTC.
                prazo=datetime.combine(certificacao.valida_ate, time.max, tzinfo=timezone.utc),
            )
        )
    return condicoes
