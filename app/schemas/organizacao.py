"""Schemas de unidade, área e equipamento."""

from pydantic import BaseModel, Field

from app.models.enums import Criticidade, TipoUnidade
from app.schemas.base import ORMDatado


class UnidadeCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    identificador_operacional: str = Field(min_length=1, max_length=30)
    tipo: TipoUnidade
    ativa: bool = True


class UnidadeRead(ORMDatado):
    id: int
    nome: str
    identificador_operacional: str
    tipo: TipoUnidade
    ativa: bool


class AreaCreate(BaseModel):
    unidade_id: int
    nome: str = Field(min_length=1, max_length=120)
    codigo: str = Field(min_length=1, max_length=20)


class AreaRead(ORMDatado):
    id: int
    unidade_id: int
    nome: str
    codigo: str


class EquipamentoCreate(BaseModel):
    area_id: int
    tag: str = Field(min_length=1, max_length=40)
    descricao: str = Field(min_length=1, max_length=200)
    criticidade: Criticidade


class EquipamentoRead(ORMDatado):
    id: int
    area_id: int
    tag: str
    descricao: str
    criticidade: Criticidade
