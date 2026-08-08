"""Sincronização offline: a edição atrasada nunca atropela em silêncio.

O cenário real é o do tablet: alguém abre o rascunho no convés, perde sinal, corrige, e o
envio só sai meia hora depois. Nesse meio-tempo outra pessoa pode ter mexido na mesma PT. O
que não pode acontecer é a correção atrasada apagar a alteração da outra sem ninguém ficar
sabendo — é o teste que o contrato do projeto exige desde o L0.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Area, ModeloPT, PermissaoTrabalho, Unidade, Usuario
from app.models.enums import PerfilUsuario, TipoTrabalho, TipoUnidade
from app.models.tipos import agora_utc


@pytest.fixture
def rascunho(
    client: TestClient, db: Session,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> dict:
    """Uma PT em rascunho, e o corpo de correção pronto para ser reenviado."""
    unidade = Unidade(
        nome="FPSO Alfa", identificador_operacional="FPSO-A", tipo=TipoUnidade.FPSO
    )
    db.add(unidade)
    db.flush()
    area = Area(unidade_id=unidade.id, nome="Convés", codigo="CV")
    modelo = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE, nome="quente", campos=[])
    db.add_all([area, modelo])
    db.commit()

    criar_usuario(matricula="70001", unidade_id=unidade.id)
    criar_usuario(matricula="70002", perfil=PerfilUsuario.ADMIN, unidade_id=unidade.id)
    dono = autenticar("70001")
    inicio = agora_utc()

    pt = client.post(
        "/pts",
        headers=dono,
        json={
            "tipo_trabalho": TipoTrabalho.TRABALHO_A_QUENTE.value,
            "modelo_pt_id": modelo.id,
            "unidade_id": unidade.id,
            "area_id": area.id,
            "descricao": "Solda em suporte de tubulação",
            "valida_de": inicio.isoformat(),
            "valida_ate": (inicio + timedelta(hours=8)).isoformat(),
        },
    ).json()

    def correcao(descricao: str, visto_em: str) -> dict:
        return {
            "tipo_trabalho": pt["tipo_trabalho"],
            "modelo_pt_id": pt["modelo_pt_id"],
            "area_id": pt["area_id"],
            "descricao": descricao,
            "valida_de": pt["valida_de"],
            "valida_ate": pt["valida_ate"],
            "visto_em": visto_em,
        }

    return {"pt": pt, "dono": dono, "admin": autenticar("70002"), "correcao": correcao}


def _codigos(resposta) -> set[str]:
    return {p["codigo"] for p in resposta.json()["detail"]}


def test_edicao_offline_nao_sobrescreve_alteracao_remota(
    client: TestClient, db: Session, rascunho: dict
) -> None:
    """O teste obrigatório do contrato.

    O tablet leu a PT, ficou sem sinal e corrigiu. Enquanto isso, o admin corrigiu a mesma PT
    pela rede. Quando o tablet finalmente envia, a edição dele **não pode** apagar a do admin.
    """
    pt = rascunho["pt"]
    visto_pelo_tablet = pt["atualizado_em"]

    # Chegou primeiro, pela rede.
    pela_rede = client.patch(
        f"/pts/{pt['id']}",
        headers=rascunho["admin"],
        json=rascunho["correcao"]("Corrigida na sala de controle", visto_pelo_tablet),
    )
    assert pela_rede.status_code == 200, pela_rede.text

    # O tablet reconecta e envia o que editou sobre a leitura antiga.
    atrasada = client.patch(
        f"/pts/{pt['id']}",
        headers=rascunho["dono"],
        json=rascunho["correcao"]("Corrigida no convés", visto_pelo_tablet),
    )

    assert atrasada.status_code == 409
    assert "edicao_desatualizada" in _codigos(atrasada)

    db.expire_all()
    # O que estava gravado continua gravado: nada foi apagado em silêncio.
    assert db.get(PermissaoTrabalho, pt["id"]).descricao == "Corrigida na sala de controle"


def test_o_conflito_diz_quando_a_pt_mudou(client: TestClient, rascunho: dict) -> None:
    """Recusar não basta: quem está a bordo precisa saber o que fazer em seguida."""
    pt = rascunho["pt"]
    client.patch(
        f"/pts/{pt['id']}",
        headers=rascunho["admin"],
        json=rascunho["correcao"]("Primeira", pt["atualizado_em"]),
    )

    atrasada = client.patch(
        f"/pts/{pt['id']}",
        headers=rascunho["dono"],
        json=rascunho["correcao"]("Segunda", pt["atualizado_em"]),
    )

    mensagem = atrasada.json()["detail"][0]["mensagem"]
    assert "Recarregue" in mensagem


def test_reenviar_sobre_a_leitura_nova_passa(
    client: TestClient, db: Session, rascunho: dict
) -> None:
    """O caminho de saída do conflito: recarregar e reenviar resolve, sem gambiarra."""
    pt = rascunho["pt"]
    client.patch(
        f"/pts/{pt['id']}",
        headers=rascunho["admin"],
        json=rascunho["correcao"]("Corrigida na sala de controle", pt["atualizado_em"]),
    )

    atual = client.get(f"/pts/{pt['id']}", headers=rascunho["dono"]).json()
    reenvio = client.patch(
        f"/pts/{pt['id']}",
        headers=rascunho["dono"],
        json=rascunho["correcao"]("Corrigida no convés", atual["atualizado_em"]),
    )

    assert reenvio.status_code == 200, reenvio.text
    db.expire_all()
    assert db.get(PermissaoTrabalho, pt["id"]).descricao == "Corrigida no convés"


def test_edicao_sem_dizer_o_que_viu_e_recusada(client: TestClient, rascunho: dict) -> None:
    """Cliente que não informa `visto_em` não tem como afirmar que não atropelou ninguém."""
    pt = rascunho["pt"]
    corpo = rascunho["correcao"]("Sem base", pt["atualizado_em"])
    corpo.pop("visto_em")

    resposta = client.patch(f"/pts/{pt['id']}", headers=rascunho["dono"], json=corpo)

    assert resposta.status_code == 422


def test_reenvio_identico_tambem_e_recusado(
    client: TestClient, db: Session, rascunho: dict
) -> None:
    """A fila offline pode reenviar o mesmo pedido depois de já ter conseguido.

    A segunda passagem é recusada: o servidor não sabe se é repetição ou se é alguém gravando
    por cima de uma leitura velha, e tratar as duas como iguais é justamente o que abriria a
    porta para o atropelo silencioso.
    """
    pt = rascunho["pt"]
    corpo = rascunho["correcao"]("Corrigida no convés", pt["atualizado_em"])

    primeira = client.patch(f"/pts/{pt['id']}", headers=rascunho["dono"], json=corpo)
    segunda = client.patch(f"/pts/{pt['id']}", headers=rascunho["dono"], json=corpo)

    assert primeira.status_code == 200
    assert segunda.status_code == 409
    assert "edicao_desatualizada" in _codigos(segunda)
    db.expire_all()
    assert db.get(PermissaoTrabalho, pt["id"]).descricao == "Corrigida no convés"
