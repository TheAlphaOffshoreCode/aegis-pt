"""Schemas Pydantic da API."""

from app.schemas.auditoria import AlertaRead, AuditEventRead
from app.schemas.organizacao import (
    AreaCreate,
    AreaRead,
    EquipamentoCreate,
    EquipamentoRead,
    UnidadeCreate,
    UnidadeRead,
)
from app.schemas.permissao import (
    AnexoRead,
    AssinaturaRead,
    ModeloPTCreate,
    ModeloPTRead,
    PermissaoTrabalhoCreate,
    PermissaoTrabalhoRead,
    PTEquipeCreate,
    PTEquipeRead,
    PTVersaoRead,
)
from app.schemas.pessoa import (
    CertificacaoCreate,
    CertificacaoRead,
    UsuarioCreate,
    UsuarioRead,
)

__all__ = [
    "AlertaRead",
    "AnexoRead",
    "AreaCreate",
    "AreaRead",
    "AssinaturaRead",
    "AuditEventRead",
    "CertificacaoCreate",
    "CertificacaoRead",
    "EquipamentoCreate",
    "EquipamentoRead",
    "ModeloPTCreate",
    "ModeloPTRead",
    "PTEquipeCreate",
    "PTEquipeRead",
    "PTVersaoRead",
    "PermissaoTrabalhoCreate",
    "PermissaoTrabalhoRead",
    "UnidadeCreate",
    "UnidadeRead",
    "UsuarioCreate",
    "UsuarioRead",
]
