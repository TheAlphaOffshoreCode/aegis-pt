"""Pendência: o que impede uma PT de seguir, dito de forma estruturada.

Mensagem solta não serve. A tela precisa saber onde marcar o erro, o motor de regras precisa
saber se bloqueia ou só avisa, e a trilha precisa saber de quem era a responsabilidade.
"""

from dataclasses import asdict, dataclass
from enum import StrEnum

from app.models.enums import PerfilUsuario


class Severidade(StrEnum):
    BLOQUEANTE = "bloqueante"
    ATENCAO = "atencao"


@dataclass(frozen=True)
class Pendencia:
    codigo: str
    severidade: Severidade
    mensagem: str
    campo: str | None = None
    responsavel: PerfilUsuario | None = None

    def como_dict(self) -> dict:
        """Forma serializável, para o corpo do 409."""
        return asdict(self)


def bloqueiam(pendencias: list[Pendencia]) -> list[Pendencia]:
    """Só as bloqueantes. Pendência de atenção informa, não impede."""
    return [p for p in pendencias if p.severidade == Severidade.BLOQUEANTE]


class ConflitoDeNegocio(Exception):
    """Pendência bloqueante ou transição inválida.

    Vira `409` com a lista estruturada num handler único, para nenhuma rota inventar o
    próprio formato de conflito.
    """

    def __init__(self, pendencias: list[Pendencia]) -> None:
        self.pendencias = pendencias
        super().__init__(f"{len(pendencias)} pendência(s) bloqueante(s)")
