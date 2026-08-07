"""Modelos SQLAlchemy. Todo modelo novo precisa ser importado aqui para entrar no metadata."""

from app.models.auditoria import Alerta, AuditEvent
from app.models.organizacao import Area, Equipamento, Unidade
from app.models.permissao import (
    Anexo,
    Assinatura,
    ModeloPT,
    PermissaoTrabalho,
    PTEquipe,
    PTVersao,
)
from app.models.pessoa import Certificacao, Usuario

__all__ = [
    "Alerta",
    "Anexo",
    "Area",
    "Assinatura",
    "AuditEvent",
    "Certificacao",
    "Equipamento",
    "ModeloPT",
    "PTEquipe",
    "PTVersao",
    "PermissaoTrabalho",
    "Unidade",
    "Usuario",
]
