"""Conferência do conteúdo real do arquivo enviado.

A extensão é o que o cliente afirma; os primeiros bytes são o que o arquivo é. Um executável
renomeado para `.pdf` passa por qualquer allowlist de extensão — e este anexo vai ser servido
de volta depois, para alguém abrir a bordo.

Não substitui a allowlist de extensão: as duas precisam concordar. Extensão errada com
conteúdo certo também é recusa, porque o navegador de quem baixa decide pelo nome.
"""

# Assinaturas dos únicos três formatos aceitos. Deliberadamente curtas e exatas: heurística
# que "tenta adivinhar" o formato é o oposto do que se quer numa fronteira de confiança.
ASSINATURAS: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}

# O maior prefixo que precisamos olhar. O chamador já lê em blocos bem maiores que isto.
BYTES_NECESSARIOS = max(len(a) for assinaturas in ASSINATURAS.values() for a in assinaturas)


def confere(inicio: bytes, media_type: str) -> bool:
    """O começo do arquivo corresponde ao tipo que a extensão prometeu?

    Tipo desconhecido devolve `False` — fechar por omissão é a única postura defensável aqui.
    """
    assinaturas = ASSINATURAS.get(media_type)
    if not assinaturas:
        return False
    return any(inicio.startswith(assinatura) for assinatura in assinaturas)
