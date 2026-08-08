"""Indicadores operacionais. Todo número aqui é um `COUNT` do banco.

Isso é a regra 2 aplicada a um lugar onde ela é fácil de esquecer: um painel parece inofensivo
até alguém decidir turno com base nele. Nenhum destes valores é estimado, arredondado ou
inferido — cada um é uma contagem, no escopo de quem perguntou (regra 5), e a mesma pergunta
feita duas vezes dá o mesmo número.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auditoria import Alerta
from app.models.enums import EstadoPT, StatusAlerta
from app.models.permissao import PermissaoTrabalho
from app.models.pessoa import Usuario
from app.models.tipos import agora_utc
from app.services import alertas as servico_alertas
from app.services.permissoes import aplicar_escopo

# Horizonte do indicador de janelas fechando. Um turno inteiro: é o que quem monta a
# programação do dia seguinte precisa enxergar.
HORAS_DE_HORIZONTE = 24


@dataclass
class Indicadores:
    pts_por_estado: dict[str, int] = field(default_factory=dict)
    pts_por_tipo: dict[str, int] = field(default_factory=dict)
    em_execucao: int = 0
    janelas_fechando: int = 0
    vencidas_em_execucao: int = 0
    alertas_por_nivel: dict[int, int] = field(default_factory=dict)
    alertas_abertos: int = 0
    total_de_pts: int = 0


def _contar(db: Session, usuario: Usuario, *condicoes) -> int:
    consulta = aplicar_escopo(select(func.count()).select_from(PermissaoTrabalho), usuario)
    for condicao in condicoes:
        consulta = consulta.where(condicao)
    return db.scalar(consulta) or 0


def calcular(db: Session, usuario: Usuario) -> Indicadores:
    """Fotografia da operação no escopo do usuário, agora."""
    agora = agora_utc()
    horizonte = agora + timedelta(hours=HORAS_DE_HORIZONTE)

    por_estado = db.execute(
        aplicar_escopo(
            select(PermissaoTrabalho.estado, func.count()).select_from(PermissaoTrabalho),
            usuario,
        ).group_by(PermissaoTrabalho.estado)
    ).all()
    por_tipo = db.execute(
        aplicar_escopo(
            select(PermissaoTrabalho.tipo_trabalho, func.count()).select_from(
                PermissaoTrabalho
            ),
            usuario,
        ).group_by(PermissaoTrabalho.tipo_trabalho)
    ).all()

    por_nivel = db.execute(
        servico_alertas.aplicar_escopo(
            select(Alerta.nivel_escalonamento, func.count()).select_from(Alerta), usuario
        )
        .where(Alerta.status != StatusAlerta.RESOLVIDO)
        .group_by(Alerta.nivel_escalonamento)
    ).all()

    return Indicadores(
        pts_por_estado={str(estado): quantidade for estado, quantidade in por_estado},
        pts_por_tipo={str(tipo): quantidade for tipo, quantidade in por_tipo},
        em_execucao=_contar(db, usuario, PermissaoTrabalho.estado == EstadoPT.EM_EXECUCAO),
        janelas_fechando=_contar(
            db,
            usuario,
            PermissaoTrabalho.estado == EstadoPT.EM_EXECUCAO,
            PermissaoTrabalho.valida_ate > agora,
            PermissaoTrabalho.valida_ate <= horizonte,
        ),
        # Separado do anterior de propósito: uma janela que já fechou com gente trabalhando
        # não é "quase vencendo", é outra coisa, e some no meio de uma contagem só.
        vencidas_em_execucao=_contar(
            db,
            usuario,
            PermissaoTrabalho.estado == EstadoPT.EM_EXECUCAO,
            PermissaoTrabalho.valida_ate <= agora,
        ),
        alertas_por_nivel={nivel: quantidade for nivel, quantidade in por_nivel},
        alertas_abertos=sum(quantidade for _, quantidade in por_nivel),
        total_de_pts=_contar(db, usuario),
    )
