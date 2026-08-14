"""Quem assina, que não é necessariamente quem abriu a sessão.

O tablet do convés é compartilhado: uma pessoa o destrava e passa a manhã com ele na mão,
enquanto o soldador, o técnico de segurança e a coordenadora assinam cada um a sua etapa. Se a
autoria viesse do token, todas as assinaturas do dia sairiam no nome de quem destravou — e a
trilha registraria uma autoria que não aconteceu, que é exatamente o que ela existe para
impedir (regra 6).

Daí a separação: o **token** define o que se enxerga (regra 5), e o **PIN** define quem assina.
São credenciais diferentes porque respondem perguntas diferentes.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pessoa import Usuario
from app.rules.pendencias import ConflitoDeNegocio, bloqueio
from app.security.credenciais import gastar_tempo_de_verificacao, verificar_senha
from app.security.dependencias import unidades_visiveis
from app.security.limite import ASSINATURA, chave_do_pedido

# Uma mensagem só para todos os modos de falhar: matrícula que não existe, PIN errado, conta
# desativada e pessoa sem PIN cadastrado respondem igual. Distinguir os casos entregaria, a quem
# souber uma matrícula, se aquela pessoa assina ou não — e a matrícula está estampada no crachá.
#
# A segunda frase existe porque a recusa precisa ser acionável sem ser um oráculo: quem nunca
# recebeu PIN descobre o que fazer, e quem está testando matrículas alheias não aprende nada.
_RECUSA = (
    "Matrícula ou PIN de assinatura não confere. Se você ainda não tem PIN, procure a "
    "coordenação da unidade."
)


def identificar_assinante(
    db: Session, *, matricula: str, pin: str, ip: str | None = None
) -> Usuario:
    """Confirma quem está assinando, ou recusa sem dizer qual parte falhou.

    Devolve o usuário confirmado. A conferência de papel, de segregação de funções e de risco
    continua no motor de regras: aqui só se responde "esta pessoa é mesmo quem diz ser".
    """
    chave = chave_do_pedido(ip, matricula)
    ASSINATURA.exigir(chave)
    ASSINATURA.registrar(chave)

    usuario = db.scalar(select(Usuario).where(Usuario.matricula == matricula))

    # O Argon2 descartável mantém o tempo de resposta igual quando a matrícula não existe.
    # Sem ele, medir a resposta diria quem está cadastrado a bordo.
    if usuario is None or not usuario.ativo or not usuario.pin_hash:
        gastar_tempo_de_verificacao()
        raise ConflitoDeNegocio([bloqueio("assinante_nao_confirmado", _RECUSA, campo="pin")])

    if not verificar_senha(pin, usuario.pin_hash):
        raise ConflitoDeNegocio([bloqueio("assinante_nao_confirmado", _RECUSA, campo="pin")])

    ASSINATURA.liberar(chave)
    return usuario


def assinante_alcanca(usuario: Usuario, unidade_id: int) -> bool:
    """A pessoa que assina precisa alcançar a unidade da PT, como qualquer leitor dela.

    Sem isto, o PIN viraria um atalho por fora do escopo: bastaria abrir a sessão numa unidade
    e assinar documento de outra, coisa que a mesma pessoa não conseguiria nem ler pela API.
    """
    visiveis = unidades_visiveis(usuario)
    return visiveis is None or unidade_id in visiveis
