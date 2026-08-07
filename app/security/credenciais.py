"""Prova de identidade: hash de senha e token de sessão.

Nada aqui toca o banco ou o HTTP — é função pura, para poder ser testada sozinha.
"""

from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from app.config import get_settings
from app.models.tipos import agora_utc

ALGORITMO = "HS256"

_hasher = PasswordHasher()

# Hash descartável, usado só para gastar o mesmo tempo quando a matrícula não existe.
_HASH_FALSO = _hasher.hash("matricula-inexistente")


def gerar_hash(senha: str) -> str:
    """Hash Argon2id da senha. O texto puro nunca é guardado nem registrado em log."""
    return _hasher.hash(senha)


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    """Confere a senha. Hash vazio ou corrompido é recusa, nunca exceção vazando."""
    if not hash_armazenado:
        return False
    try:
        return _hasher.verify(hash_armazenado, senha)
    except Argon2Error:
        return False


def gastar_tempo_de_verificacao() -> None:
    """Roda um Argon2 descartável.

    Sem isto, matrícula inexistente responde muito mais rápido que senha errada, e o
    tempo de resposta vira um oráculo de quem existe a bordo.
    """
    verificar_senha("senha-qualquer", _HASH_FALSO)


def criar_token(usuario_id: int) -> str:
    """Token de sessão. Carrega só o id — perfil e lotação são lidos do banco a cada uso.

    Perfil embutido no token continuaria valendo depois de ser revogado, por até um turno.
    """
    agora = agora_utc()
    configuracao = get_settings()
    payload = {
        "sub": str(usuario_id),
        "iat": agora,
        "exp": agora + timedelta(minutes=configuracao.token_expiracao_minutos),
    }
    return jwt.encode(payload, configuracao.secret_key, algorithm=ALGORITMO)


def ler_token(token: str) -> dict:
    """Valida assinatura e expiração. Levanta `jwt.PyJWTError` se o token não presta."""
    return jwt.decode(
        token,
        get_settings().secret_key,
        # Lista explícita: sem ela um token forjado com `alg: none` seria aceito.
        algorithms=[ALGORITMO],
    )
