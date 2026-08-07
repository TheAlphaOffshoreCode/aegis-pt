"""Validações de fronteira: o que a API recusa antes de qualquer regra de negócio rodar."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.enums import TipoTrabalho
from app.schemas import CertificacaoCreate, PermissaoTrabalhoCreate

AGORA = datetime(2026, 8, 7, 8, 0)


def _pt(**ajustes) -> dict:
    base = {
        "tipo_trabalho": TipoTrabalho.TRABALHO_A_QUENTE,
        "modelo_pt_id": 1,
        "unidade_id": 1,
        "area_id": 1,
        "descricao": "Corte e solda em tubulação",
        "valida_de": AGORA,
        "valida_ate": AGORA + timedelta(hours=8),
    }
    return base | ajustes


def test_pt_recusa_janela_invertida() -> None:
    PermissaoTrabalhoCreate(**_pt())  # janela normal passa

    with pytest.raises(ValidationError):
        PermissaoTrabalhoCreate(**_pt(valida_ate=AGORA - timedelta(hours=1)))


def test_pt_nao_aceita_estado_nem_numero_vindos_do_cliente() -> None:
    """Quem decide o estado é o servidor; campo extra é ignorado, nunca aplicado."""
    pt = PermissaoTrabalhoCreate(**_pt(), estado="LIBERACAO", numero="PT-FALSA-0001")

    assert not hasattr(pt, "estado")
    assert not hasattr(pt, "numero")


def test_certificacao_recusa_validade_anterior_a_emissao() -> None:
    with pytest.raises(ValidationError):
        CertificacaoCreate(
            usuario_id=1,
            tipo="NR-35",
            numero="35-0001",
            emitida_em="2026-08-07",
            valida_ate="2026-08-06",
        )
