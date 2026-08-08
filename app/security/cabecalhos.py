"""Cabeçalhos de segurança da resposta.

A CSP aqui é restritiva porque o produto permite que ela seja: o PWA é vanilla, sem framework,
sem build e sem CDN, então não há script de terceiro nem `style` inline para acomodar. Isso
também é o que torna aceitável o token viver no `localStorage` — sem script de terceiro na
origem, não há quem o leia. **No dia em que entrar um script externo, as duas decisões caem
juntas**, e é por isso que elas estão escritas no mesmo lugar.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

CSP = "; ".join(
    [
        "default-src 'self'",
        # Nem `unsafe-inline` nem `unsafe-eval`: não há um único script inline no shell.
        "script-src 'self'",
        "style-src 'self'",
        "font-src 'self'",
        "img-src 'self' data:",
        # A aplicação só fala com a própria origem. A Claude API é chamada pelo backend.
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        # Redundante com X-Frame-Options, e é o que navegador moderno de fato lê.
        "frame-ancestors 'none'",
    ]
)

CABECALHOS = {
    "Content-Security-Policy": CSP,
    # O anexo é conteúdo de terceiro; adivinhar o tipo é como um `.pdf` vira HTML executável.
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Nenhum referer para fora: a URL de uma PT já é informação da operação.
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=(), payment=()",
}


class CabecalhosDeSeguranca(BaseHTTPMiddleware):
    """Aplica os cabeçalhos em toda resposta, inclusive nas de erro."""

    def __init__(self, app, hsts: bool) -> None:
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        resposta = await call_next(request)
        for nome, valor in CABECALHOS.items():
            resposta.headers.setdefault(nome, valor)
        if self.hsts:
            # Só fora de desenvolvimento: em `localhost` sobre HTTP isto prenderia o navegador
            # num redirecionamento para HTTPS que não existe na máquina de quem desenvolve.
            resposta.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resposta
