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
from app.audit.documento import hash_do_documento
from app.audit.trilha import Contexto, registrar_evento
from app.models.tipos import agora_utc
from app.rules.exigencias import ESTADOS_QUE_OCUPAM_A_AREA
from app.rules.formulario import validar_respostas
from app.rules.motor import avaliar_pt
from app.rules.pendencias import ConflitoDeNegocio, Pendencia, bloqueiam, bloqueio
from app.schemas.permissao import (
    FiltroPT,
    PermissaoTrabalhoCreate,
    PermissaoTrabalhoUpdate,
)
from app.security.dependencias import unidades_visiveis

PERFIS_QUE_EMITEM = (
    PerfilUsuario.REQUISITANTE,
    PerfilUsuario.AREA_RESPONSAVEL,
    PerfilUsuario.COORDENADOR,
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
            bloqueio(
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
            bloqueio("modelo_invalido", "Modelo de PT inexistente ou inativo", campo="modelo_pt_id")
        )
    elif modelo.tipo_trabalho != dados.tipo_trabalho:
        pendencias.append(
            bloqueio(
                "modelo_incompativel",
                f"O modelo é de {modelo.tipo_trabalho}, não de {dados.tipo_trabalho}",
                campo="modelo_pt_id",
            )
        )

    area = db.get(Area, dados.area_id)
    if area is None or area.unidade_id != unidade_id:
        pendencias.append(
            bloqueio("area_invalida", "A área não pertence à unidade informada", campo="area_id")
        )

    if dados.equipamento_id is not None:
        equipamento = db.get(Equipamento, dados.equipamento_id)
        if equipamento is None or equipamento.area_id != dados.area_id:
            pendencias.append(
                bloqueio(
                    "equipamento_invalido",
                    "O equipamento não pertence à área informada",
                    campo="equipamento_id",
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
                bloqueio(
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
    db: Session,
    dados: PermissaoTrabalhoCreate,
    autor: Usuario,
    contexto: Contexto = Contexto(),
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
        # A trilha começa no nascimento da PT: o primeiro elo é a criação, não a primeira
        # transição — senão a origem do documento fica fora da cadeia.
        registrar_evento(
            db,
            pt=pt,
            tipo_evento="pt.criada",
            ator=autor,
            hash_documento=hash_do_documento(pt),
            estado_destino=EstadoPT.RASCUNHO,
            contexto=contexto,
        )
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
        [bloqueio("numero_em_disputa", "Não foi possível reservar o número da PT; tente de novo")]
    )


def _condicoes_do_filtro(filtro: FiltroPT) -> list:
    """Traduz o filtro em condições SQL. Campo vazio não vira condição nenhuma."""
    condicoes = []
    if filtro.numero:
        condicoes.append(PermissaoTrabalho.numero.contains(filtro.numero.upper()))
    if filtro.texto:
        # `lower()` dos dois lados: o SQLite só é insensível a maiúsculas em ASCII, e a
        # descrição vem em português. Sem isso, "SOLDA" não acha "solda".
        condicoes.append(func.lower(PermissaoTrabalho.descricao).contains(filtro.texto.lower()))
    if filtro.estado is not None:
        condicoes.append(PermissaoTrabalho.estado == filtro.estado)
    if filtro.tipo_trabalho is not None:
        condicoes.append(PermissaoTrabalho.tipo_trabalho == filtro.tipo_trabalho)
    if filtro.unidade_id is not None:
        condicoes.append(PermissaoTrabalho.unidade_id == filtro.unidade_id)
    if filtro.area_id is not None:
        condicoes.append(PermissaoTrabalho.area_id == filtro.area_id)
    if filtro.equipamento_id is not None:
        condicoes.append(PermissaoTrabalho.equipamento_id == filtro.equipamento_id)
    if filtro.requisitante_id is not None:
        condicoes.append(PermissaoTrabalho.requisitante_id == filtro.requisitante_id)
    if filtro.vigentes_em is not None:
        condicoes.append(PermissaoTrabalho.valida_de <= filtro.vigentes_em)
        condicoes.append(PermissaoTrabalho.valida_ate >= filtro.vigentes_em)
    if filtro.inicio_apos is not None:
        condicoes.append(PermissaoTrabalho.valida_de >= filtro.inicio_apos)
    if filtro.inicio_antes is not None:
        condicoes.append(PermissaoTrabalho.valida_de <= filtro.inicio_antes)
    return condicoes


def buscar_pts(
    db: Session, usuario: Usuario, filtro: FiltroPT
) -> tuple[int, Sequence[PermissaoTrabalho]]:
    """Busca paginada dentro do escopo do usuário.

    Devolve o total **antes** do recorte, senão a tela não sabe quantas páginas existem. A
    contagem passa pelo mesmo escopo e pelos mesmos filtros — contar num universo maior que o
    exibido já entregaria quantas PTs existem fora do alcance de quem perguntou.
    """
    condicoes = _condicoes_do_filtro(filtro)
    base = aplicar_escopo(select(PermissaoTrabalho), usuario).where(*condicoes)

    total = db.scalar(
        aplicar_escopo(select(func.count(PermissaoTrabalho.id)), usuario).where(*condicoes)
    )
    itens = db.scalars(
        base.order_by(PermissaoTrabalho.id.desc())
        .limit(filtro.limite)
        .offset(filtro.deslocamento)
    ).all()
    return total or 0, itens


def concorrentes_na_area(db: Session, pt: PermissaoTrabalho) -> Sequence[PermissaoTrabalho]:
    """PTs que ocupam a mesma área com janela sobreposta.

    Sobreposição é `inicio_de_uma < fim_da_outra` nos dois sentidos; comparar só os inícios
    deixa passar a PT que começou antes e ainda não terminou.
    """
    consulta = select(PermissaoTrabalho).where(
        PermissaoTrabalho.id != pt.id,
        PermissaoTrabalho.area_id == pt.area_id,
        PermissaoTrabalho.estado.in_(ESTADOS_QUE_OCUPAM_A_AREA),
        PermissaoTrabalho.valida_de < pt.valida_ate,
        PermissaoTrabalho.valida_ate > pt.valida_de,
    )
    return db.scalars(consulta).all()


def pendencias_da_pt(db: Session, pt: PermissaoTrabalho) -> list[Pendencia]:
    """Roda o motor de regras contra a PT. Só avalia — não decide nada e não grava nada."""
    return avaliar_pt(pt, concorrentes_na_area(db, pt), agora_utc())


def obter_pt(db: Session, pt_id: int, usuario: Usuario) -> PermissaoTrabalho | None:
    """PT dentro do escopo do usuário. Fora do escopo devolve `None`, e o router responde 404.

    404 e não 403: dizer "existe, mas você não pode" já responde se a PT existe.
    """
    consulta = aplicar_escopo(select(PermissaoTrabalho).where(PermissaoTrabalho.id == pt_id), usuario)
    return db.scalars(consulta).first()


def atualizar_pt(
    db: Session,
    pt: PermissaoTrabalho,
    dados: PermissaoTrabalhoUpdate,
    autor: Usuario,
    contexto: Contexto = Contexto(),
) -> PermissaoTrabalho:
    """Corrige uma PT ainda em rascunho."""
    if pt.estado != EstadoPT.RASCUNHO:
        raise ConflitoDeNegocio(
            [
                bloqueio(
                    "pt_nao_editavel",
                    f"PT em {pt.estado} não é editável; use uma transição de estado",
                )
            ]
        )
    if autor.perfil != PerfilUsuario.ADMIN and pt.requisitante_id != autor.id:
        raise ConflitoDeNegocio(
            [bloqueio("nao_e_o_requisitante", "Só o requisitante pode corrigir o rascunho")]
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
    db.flush()

    registrar_evento(
        db,
        pt=pt,
        tipo_evento="pt.editada",
        ator=autor,
        # Depois do flush: o hash precisa ser o do documento já corrigido.
        hash_documento=hash_do_documento(pt),
        estado_origem=EstadoPT.RASCUNHO,
        estado_destino=EstadoPT.RASCUNHO,
        contexto=contexto,
    )

    db.commit()
    db.refresh(pt)
    return pt
