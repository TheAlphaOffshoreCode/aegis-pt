"""Limite de tentativas por janela deslizante.

Em memória, no processo. É uma escolha, não um descuido, e o limite dela precisa estar escrito:
**com mais de um processo servindo, cada um conta separado**, então o limite efetivo é o valor
configurado multiplicado pelo número de workers. Para uma unidade offshore com um processo isso
basta; num deploy com vários, isto vira Redis — e até lá o número aqui é um piso, não um teto.

O que ele resolve de verdade: força bruta de senha e laço acidental numa rota que custa dinheiro.
O que ele não resolve: ataque distribuído de muitas origens. Para isso o lugar é a borda, não a
aplicação.
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import HTTPException, status


@dataclass(frozen=True)
class Limite:
    tentativas: int
    janela_segundos: int


class Limitador:
    """Conta tentativas por chave numa janela deslizante."""

    def __init__(self, limite: Limite) -> None:
        self.limite = limite
        self._marcas: dict[str, deque[float]] = defaultdict(deque)

    def _limpar(self, marcas: deque[float], agora: float) -> None:
        while marcas and agora - marcas[0] > self.limite.janela_segundos:
            marcas.popleft()

    def espera(self, chave: str, agora: float | None = None) -> int:
        """Quantos segundos faltam até a chave poder tentar de novo. Zero se pode agora."""
        agora = time.monotonic() if agora is None else agora
        marcas = self._marcas[chave]
        self._limpar(marcas, agora)
        if len(marcas) < self.limite.tentativas:
            return 0
        return max(1, int(self.limite.janela_segundos - (agora - marcas[0])) + 1)

    def registrar(self, chave: str, agora: float | None = None) -> None:
        """Contabiliza uma tentativa."""
        agora = time.monotonic() if agora is None else agora
        marcas = self._marcas[chave]
        self._limpar(marcas, agora)
        marcas.append(agora)

    def liberar(self, chave: str) -> None:
        """Zera a contagem — usado quando a tentativa deu certo."""
        self._marcas.pop(chave, None)

    def exigir(self, chave: str) -> None:
        """Barra com `429` se a chave estourou a janela."""
        segundos = self.espera(chave)
        if segundos:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tentativas demais. Aguarde e tente de novo.",
                headers={"Retry-After": str(segundos)},
            )


# Cinco tentativas de senha por minuto: sobra para quem errou o teclado com luva molhada e
# fecha a porta para quem está varrendo senha.
LOGIN = Limitador(Limite(tentativas=5, janela_segundos=60))

# As rotas de IA custam tokens e, no caso do rascunho, criam PT. Vinte por minuto é uso humano
# folgado e corta o laço acidental de um cliente com defeito.
IA = Limitador(Limite(tentativas=20, janela_segundos=60))


def chave_do_pedido(ip: str | None, identificador: str) -> str:
    """Chave por origem **e** por identidade.

    Só por IP puniria a unidade inteira atrás de um NAT; só por matrícula deixaria alguém
    varrer contas diferentes da mesma origem sem nunca estourar o limite.
    """
    return f"{ip or 'sem-ip'}|{identificador}"
