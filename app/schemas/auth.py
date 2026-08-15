"""Schemas de login e sessão."""

from pydantic import BaseModel, Field

from app.models.enums import PerfilUsuario
from app.schemas.base import ORMSchema


class LoginRequest(BaseModel):
    matricula: str = Field(min_length=1, max_length=20)
    senha: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em_minutos: int


class SessaoRead(ORMSchema):
    """Quem está autenticado e o que ele alcança. `unidades` nulo significa todas."""

    id: int
    matricula: str
    nome: str
    perfil: PerfilUsuario
    unidade_id: int | None
    unidades: list[int] | None
    # Sem default: os dois são sempre montados a partir do usuário, e um default silencioso
    # transformaria esquecer de passá-los num "tudo certo" em vez de num erro.
    #
    # A tela precisa do primeiro para mandar trocar o PIN **antes** de a pessoa descobrir na
    # recusa, com a PT aberta e o serviço parado esperando assinatura. E do segundo porque sem
    # PIN se navega e se emite rascunho, mas não se assina — melhor avisar que deixar o botão
    # falhar.
    pin_precisa_troca: bool
    tem_pin: bool


class TrocaSenhaRequest(BaseModel):
    """A senha atual não é burocracia: prova que quem digita é o dono, e não quem pegou o
    tablet destravado."""

    senha_atual: str = Field(min_length=1, max_length=200)
    senha_nova: str = Field(min_length=1, max_length=200)


class TrocaPinRequest(BaseModel):
    pin_atual: str = Field(min_length=1, max_length=32)
    pin_novo: str = Field(min_length=1, max_length=32)


class AtribuirPinRequest(BaseModel):
    """Sem segredo atual: existe exatamente para quem não tem um, ou esqueceu o que tinha."""

    pin: str = Field(min_length=1, max_length=32)


class PessoaRead(ORMSchema):
    """A pessoa vista pela coordenação, para saber a quem falta PIN.

    Sem e-mail, sem hash e sem nada além do necessário para a decisão: dar ou não dar um PIN.
    """

    id: int
    matricula: str
    nome: str
    perfil: PerfilUsuario
    unidade_id: int | None
    ativo: bool
    tem_pin: bool
    pin_precisa_troca: bool
