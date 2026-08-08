"""Regressões da varredura adversarial pós-L13.

Sete defeitos que a suíte não pegava, achados relendo o próprio código à procura do que eu
tinha errado — não do que tinha projetado. Cada teste aqui falha se a correção sair.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alerta, PermissaoTrabalho, Usuario
from app.models.enums import EstadoPT, StatusAlerta
from app.schemas.permissao import PermissaoTrabalhoUpdate, TransicaoRequest
from app.security import limite
from app.services import alertas
from tests.test_alertas import cenario, criar_pt  # noqa: F401


@pytest.fixture(autouse=True)
def _limitadores_zerados() -> None:
    limite.LOGIN._marcas.clear()
    limite.LOGIN._varrido_em = None
    limite.IA._marcas.clear()
    limite.IA._varrido_em = None


# --- 1. Alerta que reaparece depois de resolvido -------------------------------------------


def test_condicao_que_volta_reabre_o_alerta_em_vez_de_estourar(
    db: Session, cenario: dict
) -> None:
    """Era um `IntegrityError` — 500 na cara de quem chamou a sincronização.

    Caminho real: PT em execução com a janela vencida abre o alerta; suspender a PT resolve o
    alerta; retomar traz a condição de volta. O `INSERT` batia na UNIQUE de identidade.
    """
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    momento = pt.valida_ate + timedelta(hours=1)

    alertas.sincronizar(db, momento)
    pt.estado = EstadoPT.SUSPENSA
    db.commit()
    resolvido = alertas.sincronizar(db, momento)

    pt.estado = EstadoPT.EM_EXECUCAO
    db.commit()
    reaberto = alertas.sincronizar(db, momento)

    assert resolvido.resolvidos == 1
    assert reaberto.reabertos == 1
    alerta = db.scalars(select(Alerta)).one()  # uma linha só, não duas
    assert alerta.status != StatusAlerta.RESOLVIDO


def test_reabrir_preserva_desde_quando_o_problema_existe(
    db: Session, cenario: dict
) -> None:
    """Abrir outra linha faria parecer estreia o que é reincidência."""
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    momento = pt.valida_ate + timedelta(hours=1)
    alertas.sincronizar(db, momento)
    db.expire_all()
    abertura = db.scalars(select(Alerta)).one().criado_em

    pt.estado = EstadoPT.SUSPENSA
    db.commit()
    alertas.sincronizar(db, momento)
    pt.estado = EstadoPT.EM_EXECUCAO
    db.commit()
    alertas.sincronizar(db, momento)
    db.expire_all()

    assert db.scalars(select(Alerta)).one().criado_em == abertura


# --- 2. Limitador: memória e CPU ------------------------------------------------------------


def test_o_limitador_nao_cresce_sem_teto() -> None:
    """`/auth/login` é rota aberta: sem varredura, matrículas aleatórias enchem a memória."""
    limitador = limite.Limitador(limite.Limite(tentativas=5, janela_segundos=60))
    for i in range(500):
        limitador.registrar(f"1.2.3.4|{i}", agora=float(i) * 0.01)

    assert len(limitador._marcas) == 500  # tudo ainda dentro da janela

    limitador.registrar("outra", agora=10_000.0)  # relógio muito além da janela

    assert len(limitador._marcas) == 1


def test_consultar_o_limitador_nao_cria_entrada() -> None:
    """Se só perguntar alocasse, uma varredura de chaves inexistentes já encheria a memória."""
    limitador = limite.Limitador(limite.Limite(tentativas=5, janela_segundos=60))

    for i in range(1000):
        assert limitador.espera(f"nunca-vista-{i}") == 0

    assert limitador._marcas == {}


def test_a_varredura_nao_roda_a_cada_tentativa() -> None:
    """A primeira correção varria por tamanho e virava O(n²) — trocava DoS de memória por CPU.

    Com muitas chaves dentro da janela, varrer a cada registro não libera nada e custa uma
    passagem completa por tentativa.
    """
    limitador = limite.Limitador(limite.Limite(tentativas=5, janela_segundos=60))
    varreduras = []
    original = limitador._talvez_varrer

    def contando(agora: float) -> None:
        antes = limitador._varrido_em
        original(agora)
        if limitador._varrido_em != antes:
            varreduras.append(agora)

    limitador._talvez_varrer = contando
    for i in range(1000):
        limitador.registrar(f"chave-{i}", agora=float(i) * 0.01)  # 10 s no total

    # Uma janela de 60 s não cabe duas varreduras em 10 s de tráfego.
    assert len(varreduras) == 1


def test_o_limitador_continua_barrando_depois_de_varrer() -> None:
    limitador = limite.Limitador(limite.Limite(tentativas=2, janela_segundos=60))
    limitador.registrar("x", agora=1000.0)
    limitador.registrar("x", agora=1000.0)

    assert limitador.espera("x", agora=1000.0) > 0


# --- 3. Cabeçalhos num 500 de verdade -------------------------------------------------------


def test_um_500_real_ainda_leva_os_cabecalhos(client: TestClient) -> None:
    """O teste do L13 só exercitava um 401 — que é `HTTPException` e passa pela pilha.

    Um erro não tratado sobe até o `ServerErrorMiddleware`, que fica **acima** de todo
    middleware da aplicação: a resposta saía sem nenhum cabeçalho de segurança.
    """
    from app.main import app

    @app.get("/_varredura_explode", include_in_schema=False)
    def explode():
        raise RuntimeError("segredo interno: /caminho/do/servidor")

    with TestClient(app, raise_server_exceptions=False) as sem_reraise:
        resposta = sem_reraise.get("/_varredura_explode")

    assert resposta.status_code == 500
    assert b"segredo" not in resposta.content
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in resposta.headers["Content-Security-Policy"]


# --- 4. `upload_dir` dentro da pasta pública ------------------------------------------------


def test_upload_dentro_de_static_recusa_subir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Era só um comentário, e comentário não impede configuração.

    `AEGIS_UPLOAD_DIR=static/uploads` transformaria todo anexo em documento público, sem erro
    nenhum aparecendo.
    """
    from app.config import Settings

    monkeypatch.setenv("AEGIS_UPLOAD_DIR", "static/anexos")
    with pytest.raises(ValueError, match="servida publicamente"):
        Settings()


def test_upload_fora_da_pasta_publica_passa(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    monkeypatch.setenv("AEGIS_UPLOAD_DIR", "./uploads")
    assert Settings().upload_dir is not None


# --- 5. `visto_em` sem fuso ----------------------------------------------------------------


def test_visto_em_sem_fuso_e_tratado_como_utc() -> None:
    """Comparar ingênuo com aware nunca coincide: o cliente levaria 409 em toda edição."""
    base = {
        "tipo_trabalho": "trabalho_a_quente",
        "modelo_pt_id": 1,
        "area_id": 1,
        "descricao": "x",
        "valida_de": "2026-08-08T08:00:00Z",
        "valida_ate": "2026-08-08T16:00:00Z",
        "visto_em": "2026-08-08T12:00:00",
    }

    assert PermissaoTrabalhoUpdate(**base).visto_em == datetime(
        2026, 8, 8, 12, 0, tzinfo=timezone.utc
    )
    assert TransicaoRequest(
        destino="VALIDACAO", visto_em="2026-08-08T12:00:00"
    ).visto_em == datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def test_visto_em_com_fuso_e_preservado() -> None:
    assert TransicaoRequest(
        destino="VALIDACAO", visto_em="2026-08-08T12:00:00+00:00"
    ).visto_em == datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


# --- 6. Estado do cliente entre usuários ----------------------------------------------------


def test_o_cliente_separa_fila_e_cache_por_usuario() -> None:
    """Tablet de convés é compartilhado.

    Sem separar: quem entra depois lê offline as PTs de quem entrou antes, e uma correção
    enfileirada por A sairia com o token de B — a trilha registraria a autoria errada.
    """
    from pathlib import Path

    js = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "limparCacheDeDados" in js
    assert "aegis_matricula" in js
    # O envio e a pintura da fila olham só o que é do usuário atual.
    assert "for (const item of Fila.minhas())" in js
    assert "matricula: API.matricula" in js


def test_o_service_worker_revalida_o_shell() -> None:
    """Cache-first puro congelaria o aplicativo na versão instalada, sem erro aparente."""
    from pathlib import Path

    sw = Path("static/sw.js").read_text(encoding="utf-8")

    assert "cache.put(requisicao, resposta.clone())" in sw
    assert "/auth" not in sw.split("CACHEAVEL")[1].split("]")[0]
