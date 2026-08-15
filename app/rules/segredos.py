"""O que serve como senha e como PIN de assinatura.

Regra pura, no padrão do resto de `app/rules/`: recebe o segredo proposto e devolve pendências,
sem tocar banco nem HTTP. Cada limite fica testável sozinho, e a política vira um arquivo que
alguém de segurança revisa sem ler o resto do sistema.

A política do PIN é frouxa **de propósito**: quatro dígitos é pouca entropia e isso está
assumido por escrito em `docs/SECURITY.md`. Quem o defende não é o comprimento, é o limitador
de três tentativas por minuto e a trilha append-only. O que estas regras impedem é a fatia de
PINs que um atacante tentaria primeiro — e é aí que três por minuto deixaria de bastar.
"""

from app.rules.pendencias import Pendencia, bloqueio

PIN_MINIMO = 4
PIN_MAXIMO = 8
# Dez caracteres, e não catorze: a senha do convés é digitada em tablet com luva, e exigência
# alta demais é o que faz nascer o bilhete colado atrás do aparelho. Quem protege a sessão de
# verdade é ela durar um turno e o perfil ser relido do banco a cada pedido.
SENHA_MINIMA = 10


def _todos_iguais(pin: str) -> bool:
    """`0000`, `1111` — o primeiro chute de qualquer um."""
    return len(set(pin)) == 1


def _sequencial(pin: str) -> bool:
    """`1234` e `4321`: dígitos consecutivos, em qualquer direção."""
    passos = {ord(depois) - ord(antes) for antes, depois in zip(pin, pin[1:])}
    return passos in ({1}, {-1})


def avaliar_pin(pin: str, *, matricula: str) -> list[Pendencia]:
    """Pendências que impedem este PIN de ser aceito. Lista vazia significa que serve."""
    if not pin.isdigit() or not PIN_MINIMO <= len(pin) <= PIN_MAXIMO:
        # Só dígitos porque o teclado numérico é o que aparece no tablet, e um PIN que exige
        # trocar de teclado com luva molhada é um PIN que vira `1111`.
        return [
            bloqueio(
                "pin_fora_do_formato",
                f"O PIN precisa ter de {PIN_MINIMO} a {PIN_MAXIMO} dígitos, só números",
                campo="pin_novo",
            )
        ]

    pendencias = []
    if pin == matricula:
        pendencias.append(
            bloqueio(
                "pin_igual_a_matricula",
                "O PIN não pode ser a própria matrícula — ela está estampada no crachá",
                campo="pin_novo",
            )
        )
    if _todos_iguais(pin) or _sequencial(pin):
        pendencias.append(
            bloqueio(
                "pin_previsivel",
                "O PIN não pode ser uma sequência nem o mesmo dígito repetido",
                campo="pin_novo",
            )
        )
    return pendencias


def avaliar_senha(senha: str, *, matricula: str) -> list[Pendencia]:
    """Pendências que impedem esta senha de ser aceita. Lista vazia significa que serve."""
    pendencias = []
    if len(senha) < SENHA_MINIMA:
        pendencias.append(
            bloqueio(
                "senha_curta",
                f"A senha precisa de pelo menos {SENHA_MINIMA} caracteres",
                campo="senha_nova",
            )
        )
    if senha.strip() == matricula:
        pendencias.append(
            bloqueio(
                "senha_igual_a_matricula",
                "A senha não pode ser a própria matrícula",
                campo="senha_nova",
            )
        )
    return pendencias
