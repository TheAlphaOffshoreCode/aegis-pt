"""Materialização e leitura dos alertas.

A condição é calculada, o alerta é gravado. Vale a pena dizer por que os dois passos existem
em vez de um só: a **condição** é derivada do estado atual e some sozinha quando o problema é
resolvido; o **alerta** guarda o que só o banco pode guardar — que alguém já viu, que já subiu
de nível, quando apareceu pela primeira vez.

Não há daemon escondido. `sincronizar()` é uma função chamada por quem quiser (um cron, um
botão, um teste), e é **idempotente**: rodar duas vezes seguidas não muda nada, porque o nível
de escalonamento é função do relógio e não de quantas vezes ela rodou.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.models.auditoria import Alerta
from app.models.enums import EstadoPT, StatusAlerta
from app.models.permissao import PermissaoTrabalho
from app.models.pessoa import Certificacao, Usuario
from app.models.tipos import agora_utc
from app.rules import alertas as regras
from app.security.dependencias import unidades_visiveis

# Estados que não geram nem mantêm alerta: a PT já saiu do caminho crítico.
ESTADOS_ENCERRADOS = frozenset(
    {EstadoPT.ENCERRADA, EstadoPT.ARQUIVADA, EstadoPT.REJEITADA, EstadoPT.RASCUNHO}
)


@dataclass
class Sincronizacao:
    """O que a passagem fez. Útil para o cron logar e para o teste conferir."""

    abertos: int = 0
    escalonados: int = 0
    resolvidos: int = 0


def aplicar_escopo(consulta: Select, usuario: Usuario) -> Select:
    """Restringe a consulta de alertas às unidades do usuário (regra 5).

    Mesmo desenho do escopo de PT: o filtro entra na consulta. É por isso que o alerta guarda
    `unidade_id` — dá para escapar sem saber se a entidade é uma PT ou uma certificação.
    """
    unidades = unidades_visiveis(usuario)
    if unidades is None:
        return consulta
    return consulta.where(Alerta.unidade_id.in_(unidades))


def _condicoes(db: Session, agora: datetime) -> list[regras.Condicao]:
    """Carrega o que as regras precisam e as roda. Nenhuma decisão acontece aqui."""
    pts = db.scalars(
        select(PermissaoTrabalho).where(PermissaoTrabalho.estado.not_in(ESTADOS_ENCERRADOS))
    ).all()
    certificacoes = db.scalars(
        select(Certificacao).options(selectinload(Certificacao.usuario))
    ).all()
    return [
        *regras.condicoes_das_pts(pts, agora),
        *regras.condicoes_das_certificacoes(certificacoes, agora),
    ]


def sincronizar(db: Session, agora: datetime | None = None) -> Sincronizacao:
    """Abre, escalona e resolve alertas a partir das condições de agora.

    Idempotente por construção: a identidade do alerta é `(tipo, entidade, entidade_id)`, e o
    nível vem do relógio. Rodar de novo no mesmo minuto não abre nada nem sobe nada.
    """
    agora = agora or agora_utc()
    resultado = Sincronizacao()

    condicoes = {condicao.chave: condicao for condicao in _condicoes(db, agora)}
    existentes = {
        (alerta.tipo, alerta.entidade, alerta.entidade_id): alerta
        for alerta in db.scalars(
            select(Alerta).where(Alerta.status != StatusAlerta.RESOLVIDO)
        ).all()
    }

    for chave, condicao in condicoes.items():
        nivel = regras.nivel_de_escalonamento(condicao.prazo, agora)
        alerta = existentes.get(chave)
        if alerta is None:
            db.add(
                Alerta(
                    tipo=condicao.tipo,
                    entidade=condicao.entidade,
                    entidade_id=condicao.entidade_id,
                    unidade_id=condicao.unidade_id,
                    mensagem=condicao.mensagem,
                    prazo=condicao.prazo,
                    nivel_escalonamento=nivel,
                    status=(
                        StatusAlerta.ESCALONADO if nivel > 0 else StatusAlerta.ABERTO
                    ),
                )
            )
            resultado.abertos += 1
            continue

        # A mensagem é reescrita porque o texto acompanha o estado (uma PT parada há 3 dias
        # não diz o mesmo que há 1). O `criado_em` é que não se mexe: é desde quando dói.
        alerta.mensagem = condicao.mensagem
        alerta.prazo = condicao.prazo
        if nivel > alerta.nivel_escalonamento:
            alerta.nivel_escalonamento = nivel
            alerta.status = StatusAlerta.ESCALONADO
            resultado.escalonados += 1

    for chave, alerta in existentes.items():
        if chave not in condicoes and alerta.status != StatusAlerta.CANCELADO:
            # A condição sumiu: a PT foi encerrada, a certificação foi renovada. O alerta é
            # resolvido, não apagado — sumir sem deixar rastro esconderia que ele existiu.
            alerta.status = StatusAlerta.RESOLVIDO
            resultado.resolvidos += 1

    db.commit()
    return resultado


def listar(
    db: Session,
    usuario: Usuario,
    tipo: str | None = None,
    status: StatusAlerta | None = None,
    nivel_minimo: int | None = None,
) -> list[Alerta]:
    """Alertas do escopo do usuário, mais recentes por último dentro de cada nível."""
    consulta = aplicar_escopo(select(Alerta), usuario)
    if tipo:
        consulta = consulta.where(Alerta.tipo == tipo)
    if status:
        consulta = consulta.where(Alerta.status == status)
    if nivel_minimo is not None:
        consulta = consulta.where(Alerta.nivel_escalonamento >= nivel_minimo)
    # Quem está mais alto na escada primeiro: é a ordem em que alguém a bordo deve olhar.
    consulta = consulta.order_by(Alerta.nivel_escalonamento.desc(), Alerta.prazo)
    return list(db.scalars(consulta).all())
