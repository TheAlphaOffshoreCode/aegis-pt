"""Motor de regras da PT.

Funções puras: recebem a PT (e as PTs concorrentes já carregadas) e devolvem pendências.
Nenhuma consulta ao banco acontece aqui — quem busca é o serviço. Assim cada regra é testável
sozinha, e nenhum número de segurança depende de estado invisível.

Regra 2 vale integralmente: prazo, contagem e validade saem daqui, calculados e testados.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from app.models.enums import PapelAssinatura, PerfilUsuario
from app.models.permissao import Anexo, PermissaoTrabalho
from app.models.pessoa import Usuario
from app.rules.exigencias import (
    ANEXOS_EXIGIDOS,
    CERTIFICACAO_EXIGIDA,
    DIAS_DE_AVISO_DE_VENCIMENTO,
    DURACAO_MAXIMA_HORAS,
    DURACAO_MAXIMA_PADRAO_HORAS,
    TRABALHOS_INCOMPATIVEIS,
)
from app.rules.pendencias import Pendencia, aviso, bloqueio

PAPEL_EXIGE_PERFIL: dict[PapelAssinatura, PerfilUsuario] = {
    PapelAssinatura.REQUISITANTE: PerfilUsuario.REQUISITANTE,
    PapelAssinatura.EXECUTANTE: PerfilUsuario.EXECUTANTE,
    PapelAssinatura.TECNICO_SEGURANCA: PerfilUsuario.TECNICO_SEGURANCA,
    PapelAssinatura.AREA_RESPONSAVEL: PerfilUsuario.AREA_RESPONSAVEL,
    PapelAssinatura.COORDENADOR: PerfilUsuario.COORDENADOR,
    PapelAssinatura.OIM: PerfilUsuario.OIM,
}


def certificacoes_da_equipe(pt: PermissaoTrabalho) -> list[Pendencia]:
    """Cada executante precisa da habilitação do tipo de trabalho, válida até o fim da janela.

    A validade é conferida contra `valida_ate`, e não contra hoje: certificado que vence no meio
    do serviço deixa o trabalhador sem habilitação exatamente enquanto ele está exposto.
    """
    exigida = CERTIFICACAO_EXIGIDA.get(pt.tipo_trabalho)
    if exigida is None:
        return []

    fim_da_janela = pt.valida_ate.date()
    pendencias: list[Pendencia] = []

    if not pt.equipe:
        return [
            bloqueio(
                "equipe_vazia",
                "Nenhum executante foi alocado à PT",
                responsavel=PerfilUsuario.REQUISITANTE,
                campo="equipe",
            )
        ]

    for membro in pt.equipe:
        certificacoes = [c for c in membro.usuario.certificacoes if c.tipo == exigida]
        if not certificacoes:
            pendencias.append(
                bloqueio(
                    "certificacao_ausente",
                    f"{membro.usuario.nome} não possui {exigida} cadastrada",
                    responsavel=PerfilUsuario.REQUISITANTE,
                    campo="equipe",
                )
            )
            continue

        mais_recente = max(certificacoes, key=lambda c: c.valida_ate)
        if mais_recente.valida_ate < fim_da_janela:
            pendencias.append(
                bloqueio(
                    "certificacao_vencida",
                    f"{exigida} de {membro.usuario.nome} vence em "
                    f"{mais_recente.valida_ate:%d/%m/%Y}, antes do fim da janela da PT",
                    responsavel=PerfilUsuario.REQUISITANTE,
                    campo="equipe",
                )
            )
        elif mais_recente.valida_ate <= fim_da_janela + timedelta(
            days=DIAS_DE_AVISO_DE_VENCIMENTO
        ):
            pendencias.append(
                aviso(
                    "certificacao_a_vencer",
                    f"{exigida} de {membro.usuario.nome} vence em "
                    f"{mais_recente.valida_ate:%d/%m/%Y}",
                    responsavel=PerfilUsuario.REQUISITANTE,
                    campo="equipe",
                )
            )

    return pendencias


def janela_de_validade(pt: PermissaoTrabalho, agora: datetime) -> list[Pendencia]:
    """A janela precisa estar aberta, caber no limite do tipo e cobrir a duração declarada."""
    pendencias: list[Pendencia] = []

    if pt.valida_ate <= agora:
        pendencias.append(
            bloqueio(
                "janela_vencida",
                f"A janela da PT terminou em {pt.valida_ate:%d/%m/%Y %H:%M}",
                responsavel=PerfilUsuario.REQUISITANTE,
                campo="valida_ate",
            )
        )

    horas = (pt.valida_ate - pt.valida_de).total_seconds() / 3600
    maximo = DURACAO_MAXIMA_HORAS.get(pt.tipo_trabalho, DURACAO_MAXIMA_PADRAO_HORAS)
    if horas > maximo:
        pendencias.append(
            bloqueio(
                "janela_excede_o_maximo",
                f"A janela tem {horas:.0f} h e o máximo para {pt.tipo_trabalho} é {maximo} h",
                responsavel=PerfilUsuario.TECNICO_SEGURANCA,
                campo="valida_ate",
            )
        )

    # Só confere se o formulário do tipo declarou a duração — nem todo modelo pergunta.
    declarada = pt.respostas.get("duracao_horas")
    if isinstance(declarada, (int, float)) and not isinstance(declarada, bool):
        if declarada > horas:
            pendencias.append(
                bloqueio(
                    "janela_menor_que_a_duracao",
                    f"A duração declarada é de {declarada:.0f} h e a janela cobre {horas:.0f} h",
                    responsavel=PerfilUsuario.REQUISITANTE,
                    campo="duracao_horas",
                )
            )

    return pendencias


def documentos_obrigatorios(pt: PermissaoTrabalho) -> list[Pendencia]:
    """Anexos exigidos pelo tipo de trabalho, presentes e dentro da validade."""
    pendencias: list[Pendencia] = []
    fim_da_janela = pt.valida_ate.date()

    for exigido in ANEXOS_EXIGIDOS.get(pt.tipo_trabalho, ()):
        candidatos: list[Anexo] = [a for a in pt.anexos if a.tipo == exigido]
        if not candidatos:
            pendencias.append(
                bloqueio(
                    "documento_ausente",
                    f"O documento {exigido.upper()} não foi anexado",
                    responsavel=PerfilUsuario.REQUISITANTE,
                    campo="anexos",
                )
            )
            continue

        vigentes = [
            a for a in candidatos if a.valido_ate is None or a.valido_ate >= fim_da_janela
        ]
        if not vigentes:
            vencimento = max(a.valido_ate for a in candidatos if a.valido_ate is not None)
            pendencias.append(
                bloqueio(
                    "documento_vencido",
                    f"O {exigido.upper()} anexado venceu em {vencimento:%d/%m/%Y}",
                    responsavel=PerfilUsuario.REQUISITANTE,
                    campo="anexos",
                )
            )

    return pendencias


def trabalhos_simultaneos(
    pt: PermissaoTrabalho, concorrentes: Sequence[PermissaoTrabalho]
) -> list[Pendencia]:
    """Recusa combinações que não podem dividir a mesma área ao mesmo tempo.

    Espera receber apenas PTs da mesma área, ocupando-a e com janela sobreposta — quem faz esse
    recorte é o serviço, porque é consulta ao banco.
    """
    pendencias: list[Pendencia] = []
    for outra in concorrentes:
        if outra.id == pt.id:
            continue
        if frozenset({pt.tipo_trabalho, outra.tipo_trabalho}) in TRABALHOS_INCOMPATIVEIS:
            pendencias.append(
                bloqueio(
                    "trabalhos_incompativeis",
                    f"{outra.numero} ({outra.tipo_trabalho}) ocupa a mesma área em janela "
                    f"sobreposta e é incompatível com {pt.tipo_trabalho}",
                    responsavel=PerfilUsuario.TECNICO_SEGURANCA,
                    campo="area_id",
                )
            )
    return pendencias


def avaliar_pt(
    pt: PermissaoTrabalho, concorrentes: Sequence[PermissaoTrabalho], agora: datetime
) -> list[Pendencia]:
    """Todas as regras de risco da PT, na ordem em que fazem sentido para quem lê a tela."""
    return [
        *janela_de_validade(pt, agora),
        *certificacoes_da_equipe(pt),
        *documentos_obrigatorios(pt),
        *trabalhos_simultaneos(pt, concorrentes),
    ]


def validar_assinatura(
    pt: PermissaoTrabalho, usuario: Usuario, papel: PapelAssinatura
) -> list[Pendencia]:
    """Segregação de funções (regra 8), no motor e não na interface.

    Quem emite não aprova a própria PT, e ninguém assina num papel que seu perfil não exerce —
    inclusive `admin`, que administra o sistema e não responde tecnicamente pelo documento.
    """
    pendencias: list[Pendencia] = []

    if usuario.id == pt.requisitante_id and papel != PapelAssinatura.REQUISITANTE:
        pendencias.append(
            bloqueio(
                "segregacao_de_funcoes",
                f"{usuario.nome} emitiu esta PT e não pode assiná-la como {papel}",
                responsavel=PerfilUsuario.COORDENADOR,
                campo="papel",
            )
        )

    perfil_exigido = PAPEL_EXIGE_PERFIL[papel]
    if usuario.perfil != perfil_exigido:
        pendencias.append(
            bloqueio(
                "papel_incompativel_com_o_perfil",
                f"Assinar como {papel} exige o perfil {perfil_exigido}, "
                f"e o perfil de {usuario.nome} é {usuario.perfil}",
                responsavel=PerfilUsuario.COORDENADOR,
                campo="papel",
            )
        )

    if not usuario.ativo:
        pendencias.append(
            bloqueio(
                "assinante_inativo",
                f"{usuario.nome} está inativo e não pode assinar",
                responsavel=PerfilUsuario.COORDENADOR,
                campo="papel",
            )
        )

    return pendencias
