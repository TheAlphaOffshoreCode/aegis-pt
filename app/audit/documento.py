"""Retrato e impressão digital da PT.

O `estado` **não** entra no retrato de propósito. O hash representa o conteúdo assinado, não a
posição no fluxo: se mudasse a cada transição, duas assinaturas da mesma versão teriam hashes
diferentes e nada poderia ser conferido depois.

A cadeia de eventos que usa estes hashes é do L6; aqui só se produz o retrato.
"""

import hashlib
import json
from typing import Any

from app.models.permissao import PermissaoTrabalho


def snapshot_da_pt(pt: PermissaoTrabalho) -> dict[str, Any]:
    """Conteúdo da PT numa forma estável e comparável entre versões."""
    return {
        "uuid": pt.uuid,
        "numero": pt.numero,
        "versao": pt.versao,
        "tipo_trabalho": str(pt.tipo_trabalho),
        "unidade_id": pt.unidade_id,
        "area_id": pt.area_id,
        "equipamento_id": pt.equipamento_id,
        "modelo_pt_id": pt.modelo_pt_id,
        "requisitante_id": pt.requisitante_id,
        "descricao": pt.descricao,
        "valida_de": pt.valida_de.isoformat(),
        "valida_ate": pt.valida_ate.isoformat(),
        "perigos": pt.perigos,
        "controles": pt.controles,
        "respostas": pt.respostas,
        # Ordenado para o hash não depender da ordem em que o banco devolveu as linhas.
        "equipe": sorted(
            ({"usuario_id": m.usuario_id, "funcao": m.funcao} for m in pt.equipe),
            key=lambda m: m["usuario_id"],
        ),
    }


def hash_do_documento(pt: PermissaoTrabalho) -> str:
    """SHA-256 do retrato canônico. `sort_keys` é o que torna o hash reprodutível."""
    canonico = json.dumps(snapshot_da_pt(pt), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def diferencas(anterior: dict[str, Any], atual: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Diff campo a campo entre dois retratos, no formato `{campo: {de, para}}`."""
    return {
        campo: {"de": anterior.get(campo), "para": atual.get(campo)}
        for campo in anterior.keys() | atual.keys()
        if anterior.get(campo) != atual.get(campo)
    }
