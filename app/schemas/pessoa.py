"""Schemas de usuário e certificação."""

from datetime import date

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.enums import PerfilUsuario, TipoCertificacao
from app.schemas.base import ORMDatado


class UsuarioCreate(BaseModel):
    matricula: str = Field(min_length=1, max_length=20)
    nome: str = Field(min_length=1, max_length=120)
    email: EmailStr
    empresa: str = Field(min_length=1, max_length=120)
    cargo: str = Field(min_length=1, max_length=80)
    perfil: PerfilUsuario
    ativo: bool = True


class UsuarioRead(ORMDatado):
    id: int
    matricula: str
    nome: str
    email: str
    empresa: str
    cargo: str
    perfil: PerfilUsuario
    ativo: bool


class CertificacaoCreate(BaseModel):
    usuario_id: int
    tipo: TipoCertificacao
    numero: str = Field(min_length=1, max_length=60)
    emitida_em: date
    valida_ate: date

    @model_validator(mode="after")
    def _validade_posterior_a_emissao(self) -> "CertificacaoCreate":
        """Certificado que vence antes de ser emitido é erro de digitação, não certificado."""
        if self.valida_ate < self.emitida_em:
            raise ValueError("valida_ate não pode ser anterior a emitida_em")
        return self


class CertificacaoRead(ORMDatado):
    id: int
    usuario_id: int
    tipo: TipoCertificacao
    numero: str
    emitida_em: date
    valida_ate: date
