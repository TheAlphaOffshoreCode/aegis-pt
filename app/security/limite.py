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
    """Conta tentativas por chave numa janela deslizante.

    A varredura do que venceu é **por tempo, no máximo uma por janela**, e não por tamanho do
    dicionário. Varrer por tamanho parece equivalente e não é: com muitas chaves ainda dentro
    da janela, toda tentativa dispararia uma passagem completa que não libera nada — trocar-se-ia
    um esgotamento de memória por um de CPU, que chega antes.
    """

    def __init__(self, limite: Limite) -> None:
        self.limite = limite
        self._marcas: dict[str, deque[float]] = defaultdict(deque)
        self._varrido_em: float | None = None

    def _limpar(self, marcas: deque[float], agora: float) -> None:
        while marcas and agora - marcas[0] > self.limite.janela_segundos:
            marcas.popleft()

    def _talvez_varrer(self, agora: float) -> None:
        """Descarta chaves sem tentativa dentro da janela, no máximo uma vez por janela.

        O custo é uma passagem O(n) por janela, e o que fica retido é o tráfego de cerca de
        duas janelas — que é o que o limitador precisa lembrar de qualquer forma.
        """
        if self._varrido_em is not None and agora - self._varrido_em < self.limite.janela_segundos:
            return
        self._varrido_em = agora
        for chave in list(self._marcas):
            marcas = self._marcas[chave]
            self._limpar(marcas, agora)
            if not marcas:
                del self._marcas[chave]

    def espera(self, chave: str, agora: float | None = None) -> int:
        """Quantos segundos faltam até a chave poder tentar de novo. Zero se pode agora.

        Consulta com `get`: só perguntar não pode criar entrada, ou uma varredura de chaves
        inexistentes encheria a memória sem nem tentar uma senha.
        """
        agora = time.monotonic() if agora is None else agora
        marcas = self._marcas.get(chave)
        if marcas is None:
            return 0
        self._limpar(marcas, agora)
        if len(marcas) < self.limite.tentativas:
            return 0
        return max(1, int(self.limite.janela_segundos - (agora - marcas[0])) + 1)

    def registrar(self, chave: str, agora: float | None = None) -> None:
        """Contabiliza uma tentativa."""
        agora = time.monotonic() if agora is None else agora
        self._talvez_varrer(agora)
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

# O PIN de assinatura é curto de propósito — quatro a seis dígitos numa luva molhada — e por
# isso precisa de um limite mais apertado que a senha: o espaço de busca de um PIN de 4 dígitos
# é dez mil, e cinco tentativas por minuto o esgotariam num fim de semana. Três por minuto e por
# matrícula transformam isso em anos, sem atrapalhar quem simplesmente errou o dedo.
ASSINATURA = Limitador(Limite(tentativas=3, janela_segundos=60))


def chave_do_pedido(ip: str | None, identificador: str) -> str:
    """Chave por origem **e** por identidade.

    Só por IP puniria a unidade inteira atrás de um NAT; só por matrícula deixaria alguém
    varrer contas diferentes da mesma origem sem nunca estourar o limite.
    """
    return f"{ip or 'sem-ip'}|{identificador}"
