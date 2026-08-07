"""Ferramentas que o modelo pode chamar. Todas somente-leitura, por construção.

Duas garantias estruturais, e nenhuma delas depende do prompt:

1. **Nenhuma ferramenta escreve.** Não há aqui `add`, `commit`, `delete` nem transição de
   estado — não existe caminho técnico pelo qual o modelo aprove, libere ou encerre uma PT
   (regra 1). Ferramenta nova neste módulo que grave algo é defeito, não decisão de produto.
2. **O escopo é fechado antes da chamada.** Cada execução recebe o `Usuario` autenticado do
   servidor e passa por `buscar_pts`/`obter_pt`, que aplicam a regra 5 na consulta. O modelo
   não escolhe por quem pergunta, e nunca vê dado fora do alcance de quem perguntou.

As ferramentas devolvem JSON cru do banco e o veredito do motor de regras. Número de segurança
nenhum é calculado aqui (regra 2): prazo, contagem e validade vêm do L4, já prontos.
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EstadoPT, TipoTrabalho
from app.models.permissao import PermissaoTrabalho
from app.models.pessoa import Usuario
from app.schemas.permissao import FiltroPT
from app.services import permissoes

DEFINICOES: list[dict[str, Any]] = [
    {
        "name": "buscar_pts",
        "description": (
            "Busca permissões de trabalho (PTs) por filtros combinados. Use para perguntas "
            "sobre quais PTs existem, quantas há, ou o que está aberto agora. Devolve os "
            "campos principais de cada PT e o total de resultados. Os filtros combinam com "
            "E; omita o que não for pedido. O resultado já vem restrito ao que o usuário "
            "que perguntou pode ver."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "Trecho a procurar na descrição do serviço",
                },
                "numero": {"type": "string", "description": "Trecho do número, ex.: PT-2026"},
                "estado": {
                    "type": "string",
                    "enum": [e.value for e in EstadoPT],
                    "description": "Estado da PT no fluxo",
                },
                "tipo_trabalho": {
                    "type": "string",
                    "enum": [t.value for t in TipoTrabalho],
                    "description": "Tipo de trabalho da PT",
                },
                "area_id": {"type": "integer", "description": "Id da área"},
                "limite": {
                    "type": "integer",
                    "description": "Máximo de PTs a devolver (1 a 50). Padrão 20.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "detalhar_pt",
        "description": (
            "Devolve uma PT inteira pelo número (ex.: PT-2026-0002): descrição, janela de "
            "validade, equipe, anexos, assinaturas e respostas do formulário. Use quando a "
            "pergunta for sobre uma PT específica."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "numero": {"type": "string", "description": "Número completo da PT"},
            },
            "required": ["numero"],
        },
    },
    {
        "name": "pendencias_da_pt",
        "description": (
            "Devolve o veredito do motor de regras para uma PT: o que impede sua liberação, "
            "com código, severidade e responsável. Use para perguntas sobre o que falta, o "
            "que está bloqueando, ou se uma PT pode ser liberada. Os prazos e validades neste "
            "resultado são calculados por código determinístico — reproduza-os como vieram e "
            "nunca recalcule por conta própria."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "numero": {"type": "string", "description": "Número completo da PT"},
            },
            "required": ["numero"],
        },
    },
]

NOMES = {definicao["name"] for definicao in DEFINICOES}


def _resumir(pt: PermissaoTrabalho) -> dict:
    return {
        "numero": pt.numero,
        "estado": str(pt.estado),
        "tipo_trabalho": str(pt.tipo_trabalho),
        "descricao": pt.descricao,
        "area_id": pt.area_id,
        "unidade_id": pt.unidade_id,
        "valida_de": pt.valida_de.isoformat(),
        "valida_ate": pt.valida_ate.isoformat(),
        "versao": pt.versao,
    }


def _por_numero(db: Session, usuario: Usuario, numero: str) -> PermissaoTrabalho | None:
    """PT pelo número, dentro do escopo. Fora dele devolve `None`, como se não existisse."""
    consulta = permissoes.aplicar_escopo(
        select(PermissaoTrabalho).where(PermissaoTrabalho.numero == numero.strip().upper()),
        usuario,
    )
    return db.scalars(consulta).first()


def executar(
    nome: str, entrada: dict, db: Session, usuario: Usuario
) -> tuple[str, list[str]]:
    """Roda uma ferramenta e devolve `(resultado em JSON, PTs que ela alcançou)`.

    A segunda parte é o que sustenta a regra 3: as fontes são colhidas **aqui**, do que o
    banco de fato devolveu, e não do que o modelo diz ter consultado.
    """
    if nome == "buscar_pts":
        filtro = FiltroPT(
            texto=entrada.get("texto"),
            numero=entrada.get("numero"),
            estado=entrada.get("estado"),
            tipo_trabalho=entrada.get("tipo_trabalho"),
            area_id=entrada.get("area_id"),
            limite=min(int(entrada.get("limite") or 20), 50),
        )
        total, itens = permissoes.buscar_pts(db, usuario, filtro)
        corpo = {"total": total, "mostrando": len(itens), "pts": [_resumir(pt) for pt in itens]}
        return json.dumps(corpo, ensure_ascii=False), [pt.numero for pt in itens]

    if nome in ("detalhar_pt", "pendencias_da_pt"):
        pt = _por_numero(db, usuario, str(entrada.get("numero", "")))
        if pt is None:
            # Mesma resposta para inexistente e fora do escopo: distinguir já diria que a PT
            # existe em algum lugar que o usuário não alcança.
            return json.dumps({"encontrada": False}, ensure_ascii=False), []

        if nome == "pendencias_da_pt":
            pendencias = permissoes.pendencias_da_pt(db, pt)
            corpo = {
                "numero": pt.numero,
                "estado": str(pt.estado),
                "pendencias": [p.como_dict() for p in pendencias],
            }
            return json.dumps(corpo, ensure_ascii=False, default=str), [pt.numero]

        corpo = _resumir(pt) | {
            "perigos": pt.perigos,
            "controles": pt.controles,
            "respostas": pt.respostas,
            "equipe": [{"usuario_id": m.usuario_id, "funcao": m.funcao} for m in pt.equipe],
            "anexos": [
                {"tipo": str(a.tipo), "nome": a.nome_arquivo, "valido_ate": a.valido_ate}
                for a in pt.anexos
            ],
            "assinaturas": [
                {"papel": str(a.papel), "etapa": str(a.estado_destino), "versao": a.versao_pt}
                for a in pt.assinaturas
            ],
        }
        return json.dumps(corpo, ensure_ascii=False, default=str), [pt.numero]

    # Só chega aqui se o modelo inventar um nome de ferramenta.
    return json.dumps({"erro": f"ferramenta desconhecida: {nome}"}, ensure_ascii=False), []
