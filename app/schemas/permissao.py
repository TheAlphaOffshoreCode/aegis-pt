"""Schemas do modelo de PT, da permissão, equipe, versões, anexos e assinaturas.

`PTVersao`, `Assinatura` e o estado da PT não têm schema de escrita de propósito: são
produzidos pelo servidor, e aceitar qualquer um deles do cliente seria deixar o navegador
escolher em que estado a permissão está.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

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


class AnexoCreate(BaseModel):
    """Metadados do anexo. O hash é calculado pelo servidor sobre o arquivo recebido."""

    tipo: TipoAnexo
    nome_arquivo: str = Field(min_length=1, max_length=255)
    valido_ate: date | None = None

    @field_validator("nome_arquivo")
    @classmethod
    def _nome_sem_caminho(cls, valor: str) -> str:
        """O L7 grava em disco: separador ou `..` no nome é path traversal esperando acontecer."""
        if "/" in valor or "\\" in valor or ".." in valor:
            raise ValueError("nome_arquivo não pode conter caminho")
        return valor


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


class AssinaturaRead(ORMSchema):
    id: int
    pt_id: int
    usuario_id: int
    papel: PapelAssinatura
    versao_pt: int
    hash_documento: str
    assinado_em: datetime
