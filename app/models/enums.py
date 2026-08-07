"""Vocabulário do domínio. O valor de cada membro é o que vai para o banco, a API e a tela."""

from enum import StrEnum


class PerfilUsuario(StrEnum):
    """Perfil de acesso. O RBAC do L2 é construído sobre estes valores."""

    REQUISITANTE = "requisitante"
    EXECUTANTE = "executante"
    TECNICO_SEGURANCA = "tecnico_seguranca"
    AREA_RESPONSAVEL = "area_responsavel"
    COORDENADOR = "coordenador"
    OIM = "oim"
    AUDITOR = "auditor"
    ADMIN = "admin"


class TipoUnidade(StrEnum):
    PLATAFORMA_FIXA = "plataforma_fixa"
    PLATAFORMA_SEMISSUBMERSIVEL = "plataforma_semissubmersivel"
    FPSO = "fpso"
    NAVIO = "navio"
    BASE_TERRESTRE = "base_terrestre"


class Criticidade(StrEnum):
    BAIXA = "baixa"
    MEDIA = "media"
    ALTA = "alta"
    CRITICA = "critica"


class TipoCertificacao(StrEnum):
    """Habilitações exigidas por tipo de trabalho. O valor é o nome oficial da norma."""

    NR_10 = "NR-10"
    NR_33 = "NR-33"
    NR_34 = "NR-34"
    NR_35 = "NR-35"
    ANAC_RPAS = "ANAC-RPAS"


class TipoTrabalho(StrEnum):
    TRABALHO_A_QUENTE = "trabalho_a_quente"
    ESPACO_CONFINADO = "espaco_confinado"
    TRABALHO_EM_ALTURA = "trabalho_em_altura"
    ICAMENTO = "icamento"
    INTERVENCAO_ELETRICA = "intervencao_eletrica"
    INSPECAO_DRONE = "inspecao_drone"


class EstadoPT(StrEnum):
    """Estados da PT. A máquina de transições é do L5 — aqui só existe o vocabulário."""

    RASCUNHO = "RASCUNHO"
    VALIDACAO = "VALIDACAO"
    ANALISE_SMS = "ANALISE_SMS"
    APROVACAO = "APROVACAO"
    LIBERACAO = "LIBERACAO"
    EM_EXECUCAO = "EM_EXECUCAO"
    ENCERRADA = "ENCERRADA"
    ARQUIVADA = "ARQUIVADA"
    SUSPENSA = "SUSPENSA"
    REJEITADA = "REJEITADA"


class TipoAnexo(StrEnum):
    APR = "apr"
    ASO = "aso"
    CERTIFICADO = "certificado"
    RELATORIO = "relatorio"
    FOTO = "foto"
    CROQUI = "croqui"


class PapelAssinatura(StrEnum):
    """Papel exercido ao assinar. Distinto do perfil: um usuário pode assinar em vários papéis."""

    REQUISITANTE = "requisitante"
    EXECUTANTE = "executante"
    TECNICO_SEGURANCA = "tecnico_seguranca"
    AREA_RESPONSAVEL = "area_responsavel"
    COORDENADOR = "coordenador"
    OIM = "oim"


class StatusAlerta(StrEnum):
    ABERTO = "aberto"
    ESCALONADO = "escalonado"
    RESOLVIDO = "resolvido"
    CANCELADO = "cancelado"
