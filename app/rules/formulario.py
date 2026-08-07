"""Validação das respostas contra o modelo de PT.

Determinístico e sem banco: recebe a definição dos campos e o que foi respondido, devolve
pendências. Nenhum número de segurança sai daqui por adivinhação — o que não casa com a
definição vira pendência, nunca um valor "corrigido".
"""

from datetime import date

from app.rules.pendencias import Pendencia, Severidade

TIPOS_DE_CAMPO = frozenset({"texto", "numero", "data", "booleano", "selecao"})


def _valor_vazio(valor: object) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _tipo_confere(tipo: str, valor: object) -> bool:
    match tipo:
        case "texto":
            return isinstance(valor, str)
        case "numero":
            # bool é subclasse de int em Python; sem esta exclusão, `true` passaria por número.
            return isinstance(valor, (int, float)) and not isinstance(valor, bool)
        case "booleano":
            return isinstance(valor, bool)
        case "data":
            if not isinstance(valor, str):
                return False
            try:
                date.fromisoformat(valor)
            except ValueError:
                return False
            return True
        case _:
            return True


def validar_respostas(campos: list[dict], respostas: dict) -> list[Pendencia]:
    """Confere as respostas contra a definição do modelo de PT."""
    pendencias: list[Pendencia] = []
    chaves_definidas = {campo["chave"] for campo in campos}

    for chave in respostas.keys() - chaves_definidas:
        pendencias.append(
            Pendencia(
                codigo="campo_desconhecido",
                severidade=Severidade.BLOQUEANTE,
                mensagem=f"O campo '{chave}' não existe no modelo desta PT",
                campo=chave,
            )
        )

    for campo in campos:
        chave = campo["chave"]
        rotulo = campo.get("rotulo", chave)
        valor = respostas.get(chave)

        if _valor_vazio(valor):
            if campo.get("obrigatorio", False):
                pendencias.append(
                    Pendencia(
                        codigo="campo_obrigatorio",
                        severidade=Severidade.BLOQUEANTE,
                        mensagem=f"'{rotulo}' é obrigatório e não foi preenchido",
                        campo=chave,
                    )
                )
            continue

        tipo = campo.get("tipo", "texto")
        if not _tipo_confere(tipo, valor):
            pendencias.append(
                Pendencia(
                    codigo="tipo_invalido",
                    severidade=Severidade.BLOQUEANTE,
                    mensagem=f"'{rotulo}' esperava um valor do tipo {tipo}",
                    campo=chave,
                )
            )
            continue

        opcoes = campo.get("opcoes")
        if tipo == "selecao" and opcoes is not None and valor not in opcoes:
            pendencias.append(
                Pendencia(
                    codigo="opcao_invalida",
                    severidade=Severidade.BLOQUEANTE,
                    mensagem=f"'{rotulo}' aceita apenas: {', '.join(map(str, opcoes))}",
                    campo=chave,
                )
            )

    return pendencias
