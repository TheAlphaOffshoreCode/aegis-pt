"""Validação do formulário dinâmico — determinística, sem banco e sem HTTP."""

from app.rules.formulario import validar_respostas

CAMPOS = [
    {"chave": "altura_metros", "rotulo": "Altura (m)", "tipo": "numero", "obrigatorio": True},
    {"chave": "ancoragem", "rotulo": "Ancoragem", "tipo": "selecao", "obrigatorio": True,
     "opcoes": ["linha_de_vida", "ponto_fixo"]},
    {"chave": "resgate", "rotulo": "Plano de resgate", "tipo": "booleano", "obrigatorio": True},
    {"chave": "inspecao", "rotulo": "Inspeção do cinto", "tipo": "data", "obrigatorio": False},
    {"chave": "observacoes", "rotulo": "Observações", "tipo": "texto", "obrigatorio": False},
]

VALIDAS = {"altura_metros": 12.5, "ancoragem": "ponto_fixo", "resgate": True}


def _codigos(respostas: dict) -> set[str]:
    return {p.codigo for p in validar_respostas(CAMPOS, respostas)}


def test_respostas_completas_nao_geram_pendencia() -> None:
    assert validar_respostas(CAMPOS, VALIDAS) == []
    assert validar_respostas(CAMPOS, VALIDAS | {"inspecao": "2026-08-01"}) == []


def test_obrigatorio_ausente_ou_em_branco_e_pendencia() -> None:
    assert _codigos({"ancoragem": "ponto_fixo", "resgate": True}) == {"campo_obrigatorio"}
    # String de espaços é o clássico que passa por "preenchido" sem preencher nada.
    assert "campo_obrigatorio" in _codigos(VALIDAS | {"observacoes": "   ", "resgate": None})


def test_booleano_nao_conta_como_numero() -> None:
    """`isinstance(True, int)` é verdadeiro em Python; sem a exclusão, `true` viraria altura."""
    assert _codigos(VALIDAS | {"altura_metros": True}) == {"tipo_invalido"}


def test_data_invalida_e_opcao_fora_da_lista_sao_pendencias() -> None:
    assert _codigos(VALIDAS | {"inspecao": "31/02/2026"}) == {"tipo_invalido"}
    assert _codigos(VALIDAS | {"ancoragem": "corda_qualquer"}) == {"opcao_invalida"}


def test_campo_fora_do_modelo_e_recusado() -> None:
    """Resposta que o modelo não prevê não pode entrar calada no JSON da PT."""
    assert _codigos(VALIDAS | {"campo_inventado": "x"}) == {"campo_desconhecido"}
