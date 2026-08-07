"""Orquestração do ciclo de vida da PT enquanto ela é rascunho.

Transições de estado, assinatura e versionamento são do L5 — aqui a PT nasce, é lida e é
corrigida, sempre em `RASCUNHO`.
"""

from datetime import datetime
from typing import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import EstadoPT, PerfilUsuario, TipoTrabalho
from app.models.organizacao import Area, Equipamento
from app.models.permissao import ModeloPT, PermissaoTrabalho, PTEquipe
from app.models.pessoa import Usuario
from app.models.tipos import agora_utc
from app.rules.formulario import validar_respostas
from app.rules.pendencias import ConflitoDeNegocio, Pendencia, Severidade, bloqueiam
from app.schemas.permissao import PermissaoTrabalhoCreate, PermissaoTrabalhoUpdate
from app.security.dependencias import unidades_visiveis

PERFIS_QUE_EMITEM = (
    PerfilUsuario.REQUISITANTE,
    PerfilUsuario.AREA_RESPONSAVEL,
    PerfilUsuario.COORDENADOR,
)


def _bloqueio(codigo: str, mensagem: str, campo: str | None = None) -> Pendencia:
    return Pendencia(
        codigo=codigo, severidade=Severidade.BLOQUEANTE, mensagem=mensagem, campo=campo
    )


def aplicar_escopo(consulta: Select, usuario: Usuario) -> Select:
    """Restringe a consulta às unidades do usuário.

    Regra 5: o filtro entra na consulta. Peneirar o resultado depois já teria lido o que o
    usuário não pode ver.
    """
    unidades = unidades_visiveis(usuario)
    if unidades is None:
        return consulta
    return consulta.where(PermissaoTrabalho.unidade_id.in_(unidades))


def proximo_numero(db: Session, ano: int) -> str:
    """Número sequencial da PT no ano, no formato `PT-AAAA-NNNN`."""
    prefixo = f"PT-{ano}-"
    ultimo = db.scalar(
        select(func.max(PermissaoTrabalho.numero)).where(
            PermissaoTrabalho.numero.startswith(prefixo)
        )
    )
    sequencial = int(ultimo.removeprefix(prefixo)) + 1 if ultimo else 1
    # ponytail: max+1 pode colidir sob emissão concorrente. Quem garante a integridade é a
    # constraint UNIQUE, e `criar_pt` refaz o número quando ela dispara. Trocar por sequência
    # do banco se emissão simultânea virar rotina.
    return f"{prefixo}{sequencial:04d}"


def _validar_lotacao(pt_unidade_id: int, usuario: Usuario) -> list[Pendencia]:
    unidades = unidades_visiveis(usuario)
    if unidades is not None and pt_unidade_id not in unidades:
        return [
            _bloqueio(
                "fora_do_escopo",
                "A unidade informada está fora da lotação do usuário",
                campo="unidade_id",
            )
        ]
    return []


def _validar_estrutura(
    db: Session, dados: PermissaoTrabalhoCreate | PermissaoTrabalhoUpdate, unidade_id: int
) -> tuple[list[Pendencia], ModeloPT | None]:
    """Confere que modelo, área e equipamento existem e conversam entre si."""
    pendencias: list[Pendencia] = []

    modelo = db.get(ModeloPT, dados.modelo_pt_id) if dados.modelo_pt_id else None
    if modelo is None or not modelo.ativo:
        pendencias.append(
            _bloqueio("modelo_invalido", "Modelo de PT inexistente ou inativo", "modelo_pt_id")
        )
    elif modelo.tipo_trabalho != dados.tipo_trabalho:
        pendencias.append(
            _bloqueio(
                "modelo_incompativel",
                f"O modelo é de {modelo.tipo_trabalho}, não de {dados.tipo_trabalho}",
                "modelo_pt_id",
            )
        )

    area = db.get(Area, dados.area_id)
    if area is None or area.unidade_id != unidade_id:
        pendencias.append(
            _bloqueio("area_invalida", "A área não pertence à unidade informada", "area_id")
        )

    if dados.equipamento_id is not None:
        equipamento = db.get(Equipamento, dados.equipamento_id)
        if equipamento is None or equipamento.area_id != dados.area_id:
            pendencias.append(
                _bloqueio(
                    "equipamento_invalido",
                    "O equipamento não pertence à área informada",
                    "equipamento_id",
                )
            )

    return pendencias, modelo


def _validar_equipe(db: Session, equipe: Sequence) -> list[Pendencia]:
    """Confere que cada membro existe e está ativo.

    Sem isto o erro só apareceria como violação de chave estrangeira no commit — um 500 no
    lugar de uma pendência que diz qual matrícula está errada.
    """
    pendencias: list[Pendencia] = []
    for membro in equipe:
        usuario = db.get(Usuario, membro.usuario_id)
        if usuario is None or not usuario.ativo:
            pendencias.append(
                _bloqueio(
                    "membro_invalido",
                    f"Usuário {membro.usuario_id} não existe ou está inativo",
                    campo="equipe",
                )
            )
    return pendencias


def _sincronizar_equipe(db: Session, pt: PermissaoTrabalho, equipe: Sequence) -> None:
    pt.equipe.clear()
    db.flush()
    for membro in equipe:
        db.add(PTEquipe(pt_id=pt.id, usuario_id=membro.usuario_id, funcao=membro.funcao))


def criar_pt(
    db: Session, dados: PermissaoTrabalhoCreate, autor: Usuario
) -> PermissaoTrabalho:
    """Cria a PT em `RASCUNHO`. Número, estado, versão e requisitante são do servidor."""
    pendencias = _validar_lotacao(dados.unidade_id, autor)
    estrutura, modelo = _validar_estrutura(db, dados, dados.unidade_id)
    pendencias += estrutura

    pendencias += _validar_equipe(db, dados.equipe)
    if modelo is not None:
        pendencias += validar_respostas(modelo.campos, dados.respostas)

    if bloqueiam(pendencias):
        raise ConflitoDeNegocio(bloqueiam(pendencias))

    # Ano de emissão, não da janela de validade: PT aberta em dezembro para trabalho de
    # janeiro pertence à numeração do ano em que foi emitida.
    ano = agora_utc().year

    for _ in range(3):
        pt = PermissaoTrabalho(
            numero=proximo_numero(db, ano),
            tipo_trabalho=dados.tipo_trabalho,
            estado=EstadoPT.RASCUNHO,
            modelo_pt_id=dados.modelo_pt_id,
            unidade_id=dados.unidade_id,
            area_id=dados.area_id,
            equipamento_id=dados.equipamento_id,
            # Do usuário autenticado, nunca do corpo: quem emite é quem está logado.
            requisitante_id=autor.id,
            descricao=dados.descricao,
            valida_de=dados.valida_de,
            valida_ate=dados.valida_ate,
            perigos=dados.perigos,
            controles=dados.controles,
            respostas=dados.respostas,
        )
        db.add(pt)
        db.flush()
        _sincronizar_equipe(db, pt, dados.equipe)
        try:
            db.commit()
        except IntegrityError:
            # Outra emissão levou este número. Estrutura e equipe já foram validadas acima,
            # então a disputa pelo `numero` é o que sobra para a UNIQUE recusar.
            db.rollback()
            continue
        db.refresh(pt)
        return pt

    raise ConflitoDeNegocio(
        [_bloqueio("numero_em_disputa", "Não foi possível reservar o número da PT; tente de novo")]
    )


def listar_pts(
    db: Session,
    usuario: Usuario,
    estado: EstadoPT | None = None,
    tipo_trabalho: TipoTrabalho | None = None,
    vigentes_em: datetime | None = None,
) -> Sequence[PermissaoTrabalho]:
    """Lista as PTs que o usuário alcança, já filtradas no banco."""
    consulta = aplicar_escopo(select(PermissaoTrabalho), usuario)
    if estado is not None:
        consulta = consulta.where(PermissaoTrabalho.estado == estado)
    if tipo_trabalho is not None:
        consulta = consulta.where(PermissaoTrabalho.tipo_trabalho == tipo_trabalho)
    if vigentes_em is not None:
        consulta = consulta.where(
            PermissaoTrabalho.valida_de <= vigentes_em,
            PermissaoTrabalho.valida_ate >= vigentes_em,
        )
    return db.scalars(consulta.order_by(PermissaoTrabalho.id.desc())).all()


def obter_pt(db: Session, pt_id: int, usuario: Usuario) -> PermissaoTrabalho | None:
    """PT dentro do escopo do usuário. Fora do escopo devolve `None`, e o router responde 404.

    404 e não 403: dizer "existe, mas você não pode" já responde se a PT existe.
    """
    consulta = aplicar_escopo(select(PermissaoTrabalho).where(PermissaoTrabalho.id == pt_id), usuario)
    return db.scalars(consulta).first()


def atualizar_pt(
    db: Session, pt: PermissaoTrabalho, dados: PermissaoTrabalhoUpdate, autor: Usuario
) -> PermissaoTrabalho:
    """Corrige uma PT ainda em rascunho."""
    if pt.estado != EstadoPT.RASCUNHO:
        raise ConflitoDeNegocio(
            [
                _bloqueio(
                    "pt_nao_editavel",
                    f"PT em {pt.estado} não é editável; use uma transição de estado",
                )
            ]
        )
    if autor.perfil != PerfilUsuario.ADMIN and pt.requisitante_id != autor.id:
        raise ConflitoDeNegocio(
            [_bloqueio("nao_e_o_requisitante", "Só o requisitante pode corrigir o rascunho")]
        )

    pendencias, modelo = _validar_estrutura(db, dados, pt.unidade_id)
    pendencias += _validar_equipe(db, dados.equipe)
    if modelo is not None:
        pendencias += validar_respostas(modelo.campos, dados.respostas)
    if bloqueiam(pendencias):
        raise ConflitoDeNegocio(bloqueiam(pendencias))

    pt.tipo_trabalho = dados.tipo_trabalho
    pt.modelo_pt_id = dados.modelo_pt_id
    pt.area_id = dados.area_id
    pt.equipamento_id = dados.equipamento_id
    pt.descricao = dados.descricao
    pt.valida_de = dados.valida_de
    pt.valida_ate = dados.valida_ate
    pt.perigos = dados.perigos
    pt.controles = dados.controles
    pt.respostas = dados.respostas
    _sincronizar_equipe(db, pt, dados.equipe)

    db.commit()
    db.refresh(pt)
    return pt
