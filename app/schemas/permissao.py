"""Schemas do modelo de PT, da permissão, equipe, versões, anexos e assinaturas.

`PTVersao`, `Assinatura` e o estado da PT não têm schema de escrita de propósito: são
produzidos pelo servidor, e aceitar qualquer um deles do cliente seria deixar o navegador
escolher em que estado a permissão está.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import EstadoPT, PapelAssinatura, TipoAnexo, TipoTrabalho
from app.schemas.base import ORMDatado, ORMSchema


class ModeloPTCreate(BaseModel):
    tipo_trabalho: TipoTrabalho
    nome: str = Field(min_length=1, max_length=120)
    versao: int = Field(default=1, ge=1)
    ativo: bool = True
    campos: list[dict] = Field(default_factory=list)
    checklist: list[dict] = Field(default_factory=list)


class ModeloPTRead(ORMDatado):
    id: int
    tipo_trabalho: TipoTrabalho
    nome: str
    versao: int
    ativo: bool
    campos: list[dict]
    checklist: list[dict]


class PTEquipeCreate(BaseModel):
    usuario_id: int
    funcao: str = Field(min_length=1, max_length=80)


class PTEquipeRead(ORMSchema):
    id: int
    pt_id: int
    usuario_id: int
    funcao: str


class _PermissaoTrabalhoEntrada(BaseModel):
    """Campos que o cliente pode informar. Número, uuid, estado e versão nunca estão aqui."""

    tipo_trabalho: TipoTrabalho
    modelo_pt_id: int
    area_id: int
    equipamento_id: int | None = None
    descricao: str = Field(min_length=1)
    valida_de: datetime
    valida_ate: datetime
    perigos: list[dict] = Field(default_factory=list)
    controles: list[dict] = Field(default_factory=list)
    respostas: dict = Field(default_factory=dict)
    equipe: list[PTEquipeCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _janela_valida(self) -> "_PermissaoTrabalhoEntrada":
        """Janela invertida deixaria a PT vencida no instante em que nasce."""
        if self.valida_ate <= self.valida_de:
            raise ValueError("valida_ate precisa ser posterior a valida_de")
        return self


class PermissaoTrabalhoCreate(_PermissaoTrabalhoEntrada):
    unidade_id: int


class PermissaoTrabalhoUpdate(_PermissaoTrabalhoEntrada):
    """Correção de rascunho. A unidade não muda: mudá-la seria emitir outra PT."""


class PermissaoTrabalhoRead(ORMDatado):
    id: int
    uuid: str
    numero: str
    tipo_trabalho: TipoTrabalho
    estado: EstadoPT
    versao: int
    modelo_pt_id: int
    unidade_id: int
    area_id: int
    equipamento_id: int | None
    requisitante_id: int
    descricao: str
    valida_de: datetime
    valida_ate: datetime
    perigos: list[dict]
    controles: list[dict]
    respostas: dict


class PTVersaoRead(ORMSchema):
    id: int
    pt_id: int
    versao: int
    snapshot: dict
    diff: dict
    autor_id: int
    motivo: str
    criado_em: datetime


class AnexoRead(ORMSchema):
    id: int
    pt_id: int
    tipo: TipoAnexo
    nome_arquivo: str
    hash_sha256: str
    valido_ate: date | None
    enviado_por_id: int
    criado_em: datetime


class PendenciaRead(BaseModel):
    """Veredito do motor de regras. `codigo` e `campo` são o que a tela usa para marcar o erro."""

    codigo: str
    severidade: str
    mensagem: str
    campo: str | None
    responsavel: str | None


class AvaliacaoRead(BaseModel):
    """Resultado da avaliação. `liberavel` é conclusão do motor, nunca opinião de modelo."""

    pt_id: int
    numero: str
    liberavel: bool
    pendencias: list[PendenciaRead]


class TransicaoRequest(BaseModel):
    """Pedido de mudança de estado. O destino é declarado; o caminho, a máquina é que conhece."""

    destino: EstadoPT
    motivo: str | None = Field(default=None, max_length=2000)
    # O navegador informa; o servidor registra como veio, sem inventar quando falta.
    geolocalizacao: str | None = Field(default=None, max_length=80)


class TransicaoDisponivel(BaseModel):
    """Um passo possível a partir do estado atual, e se este usuário pode dá-lo."""

    destino: EstadoPT
    papel: PapelAssinatura
    assina: bool
    permitida: bool


class AssinaturaRead(ORMSchema):
    id: int
    pt_id: int
    usuario_id: int
    papel: PapelAssinatura
    estado_destino: EstadoPT
    versao_pt: int
    hash_documento: str
    assinado_em: datetime
