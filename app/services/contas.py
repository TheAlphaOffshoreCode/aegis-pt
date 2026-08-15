"""Credenciais de uma conta: trocar a própria, e atribuir a de outra pessoa.

Duas operações que parecem uma. **Trocar** exige o segredo atual e é do dono; **atribuir** é da
coordenação, para quem perdeu o PIN ou nunca teve, e por isso não pode exigir o segredo antigo —
se pudesse, não serviria justamente para o caso que existe para resolver.

A diferença entre elas é o `pin_precisa_troca`: o que a coordenação entrega não assina até o
dono trocar. Ver `app/security/assinante.py`, onde a recusa acontece.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pessoa import Usuario
from app.rules.pendencias import ConflitoDeNegocio, bloqueio
from app.rules.segredos import avaliar_pin, avaliar_senha
from app.security.credenciais import gerar_hash, verificar_senha
from app.security.dependencias import unidades_visiveis

# Mesma recusa para segredo atual errado e para segredo atual ausente. Quem está aqui já provou
# a sessão, então não há identidade a proteger — o que se evita é a mensagem virar um mapa de
# quem tem PIN cadastrado quando alguém pega um tablet destravado.
_SEGREDO_ATUAL_ERRADO = "O segredo atual não confere"


def _exigir(pendencias: list) -> None:
    """Levanta só se a regra achou algo. Para recusa incondicional, `raise` direto."""
    if pendencias:
        raise ConflitoDeNegocio(pendencias)


def trocar_pin(db: Session, usuario: Usuario, *, pin_atual: str, pin_novo: str) -> None:
    """Troca o PIN de assinatura do próprio usuário.

    Funciona **inclusive** com `pin_precisa_troca` ligado — é o único caminho que funciona
    nesse estado, e é o ponto: a pessoa recebe um PIN que só serve para ser trocado.
    """
    if not verificar_senha(pin_atual, usuario.pin_hash):
        raise ConflitoDeNegocio(
            [bloqueio("pin_atual_nao_confere", _SEGREDO_ATUAL_ERRADO, campo="pin_atual")]
        )

    _exigir(avaliar_pin(pin_novo, matricula=usuario.matricula))
    if verificar_senha(pin_novo, usuario.pin_hash):
        # Trocar por si mesmo satisfaria a exigência sem mudar nada — e devolveria ao PIN
        # entregue pela coordenação a capacidade de assinar, que é o que a troca tira.
        raise ConflitoDeNegocio(
            [bloqueio("pin_repetido", "O PIN novo precisa ser diferente do atual", campo="pin_novo")]
        )

    usuario.pin_hash = gerar_hash(pin_novo)
    usuario.pin_precisa_troca = False
    db.commit()


def trocar_senha(db: Session, usuario: Usuario, *, senha_atual: str, senha_nova: str) -> None:
    """Troca a senha de sessão do próprio usuário."""
    if not verificar_senha(senha_atual, usuario.senha_hash):
        raise ConflitoDeNegocio(
            [bloqueio("senha_atual_nao_confere", _SEGREDO_ATUAL_ERRADO, campo="senha_atual")]
        )

    _exigir(avaliar_senha(senha_nova, matricula=usuario.matricula))
    if verificar_senha(senha_nova, usuario.senha_hash):
        raise ConflitoDeNegocio(
            [bloqueio("senha_repetida", "A senha nova precisa ser diferente da atual", campo="senha_nova")]
        )

    usuario.senha_hash = gerar_hash(senha_nova)
    db.commit()
    # O token continua valendo até o turno acabar, e isso é deliberado: não há lista de
    # revogação (P14), então trocar a senha não derruba sessão nenhuma — nem a de quem trocou,
    # nem a de um invasor. Quem precisa cortar acesso agora desativa a conta, que é relida do
    # banco a cada pedido. Está escrito em `docs/SECURITY.md` para ninguém supor o contrário.


def atribuir_pin(db: Session, alvo: Usuario, *, pin: str) -> None:
    """Dá um PIN a quem não tem ou perdeu. Nasce obrigado a ser trocado."""
    _exigir(avaliar_pin(pin, matricula=alvo.matricula))
    alvo.pin_hash = gerar_hash(pin)
    alvo.pin_precisa_troca = True
    db.commit()


def pessoas_no_escopo(db: Session, solicitante: Usuario) -> list[Usuario]:
    """As pessoas que o solicitante alcança, para saber a quem atribuir um PIN.

    O escopo entra **na consulta** (regra 5), como em toda listagem do projeto. Coordenação de
    uma unidade não descobre por aqui quem trabalha na outra.
    """
    consulta = select(Usuario).order_by(Usuario.nome)
    unidades = unidades_visiveis(solicitante)
    if unidades is not None:
        consulta = consulta.where(Usuario.unidade_id.in_(unidades))
    return list(db.scalars(consulta))


def obter_pessoa(db: Session, usuario_id: int, solicitante: Usuario) -> Usuario | None:
    """A pessoa pedida, ou `None` se não existe **ou** está fora do alcance de quem perguntou.

    Os dois casos devolvem a mesma coisa de propósito, e o router os transforma no mesmo 404 —
    como toda a API desde o L3, porque um 403 já confirmaria que a pessoa existe.
    """
    alvo = db.get(Usuario, usuario_id)
    unidades = unidades_visiveis(solicitante)
    if alvo is None or (unidades is not None and alvo.unidade_id not in unidades):
        return None
    return alvo
