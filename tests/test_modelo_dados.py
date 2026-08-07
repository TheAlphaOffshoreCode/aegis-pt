"""Garantias do modelo de dados do L1 — cada teste prova uma que o banco precisa sustentar."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Area,
    Assinatura,
    AuditEvent,
    Certificacao,
    Equipamento,
    ModeloPT,
    PermissaoTrabalho,
    Unidade,
    Usuario,
)
from app.models.enums import (
    EstadoPT,
    PapelAssinatura,
    PerfilUsuario,
    TipoCertificacao,
    TipoTrabalho,
    TipoUnidade,
)
from app.models.tipos import agora_utc
from app.seed import semear


def _unidade(db: Session, identificador: str = "FPSO-T-01") -> Unidade:
    unidade = Unidade(
        nome="FPSO de teste", identificador_operacional=identificador, tipo=TipoUnidade.FPSO
    )
    db.add(unidade)
    db.flush()
    return unidade


def _pt_minima(db: Session) -> PermissaoTrabalho:
    """PT válida com o mínimo de dependências, para exercitar as constraints em volta dela."""
    unidade = _unidade(db)
    area = Area(unidade_id=unidade.id, nome="Convés principal", codigo="CV")
    usuario = Usuario(
        matricula="90001",
        nome="Requisitante de teste",
        email="requisitante@exemplo.com",
        empresa="Alpha Offshore",
        cargo="Encarregado",
        perfil=PerfilUsuario.REQUISITANTE,
    )
    modelo = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_EM_ALTURA, nome="PT de altura")
    db.add_all([area, usuario, modelo])
    db.flush()

    pt = PermissaoTrabalho(
        numero="PT-2026-0001",
        tipo_trabalho=TipoTrabalho.TRABALHO_EM_ALTURA,
        modelo_pt_id=modelo.id,
        unidade_id=unidade.id,
        area_id=area.id,
        requisitante_id=usuario.id,
        descricao="Substituição de guarda-corpo no convés",
        valida_de=agora_utc(),
        valida_ate=agora_utc() + timedelta(hours=8),
    )
    db.add(pt)
    db.flush()
    return pt


def test_enum_grava_o_valor_e_nao_o_nome_do_membro(db: Session) -> None:
    """`NR-35` precisa chegar ao banco como está na norma, não como `NR_35`."""
    unidade = _unidade(db)
    usuario = Usuario(
        matricula="90002",
        nome="Executante",
        email="executante@exemplo.com",
        empresa="Contratada",
        cargo="Soldador",
        perfil=PerfilUsuario.EXECUTANTE,
    )
    db.add(usuario)
    db.flush()
    db.add(
        Certificacao(
            usuario_id=usuario.id,
            tipo=TipoCertificacao.NR_35,
            numero="35-0001",
            emitida_em=date.today() - timedelta(days=30),
            valida_ate=date.today() + timedelta(days=300),
        )
    )
    db.commit()

    assert db.scalar(text("SELECT tipo FROM certificacao")) == "NR-35"
    assert db.scalar(text("SELECT tipo FROM unidade WHERE id = :i"), {"i": unidade.id}) == "fpso"


def test_pt_nasce_em_rascunho_com_uuid_proprio(db: Session) -> None:
    """Estado inicial e identidade estável não dependem de quem inseriu a linha."""
    pt = _pt_minima(db)
    db.commit()

    assert pt.estado == "RASCUNHO"
    assert pt.versao == 1
    assert len(pt.uuid) == 36


def test_datetime_volta_do_banco_com_fuso(db: Session) -> None:
    """O SQLite não guarda offset: sem `UTCDateTime` a data lida vem naive.

    Comparar uma dessas com `agora_utc()` levanta `TypeError` — e só no banco de
    desenvolvimento, porque o PostgreSQL devolveria o valor com fuso.
    """
    pt = _pt_minima(db)
    db.commit()
    db.expire_all()

    lida = db.get(PermissaoTrabalho, pt.id)

    assert lida.valida_de.tzinfo is not None
    assert lida.criado_em.tzinfo is not None
    assert lida.valida_ate > agora_utc()  # a comparação em si é o que quebrava


def test_foreign_key_invalida_e_rejeitada(db: Session) -> None:
    """Sem `PRAGMA foreign_keys=ON` isto passaria calado e o modelo estaria mentindo."""
    db.add(Area(unidade_id=9999, nome="Área órfã", codigo="XX"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_codigo_de_area_e_unico_por_unidade_mas_nao_global(db: Session) -> None:
    primeira = _unidade(db, "FPSO-T-01")
    segunda = _unidade(db, "FPSO-T-02")
    db.add_all(
        [
            Area(unidade_id=primeira.id, nome="Convés", codigo="CV"),
            Area(unidade_id=segunda.id, nome="Convés", codigo="CV"),
        ]
    )
    db.commit()  # mesmo código em unidades diferentes é legítimo

    db.add(Area(unidade_id=primeira.id, nome="Convés duplicado", codigo="CV"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_apagar_unidade_leva_areas_e_equipamentos_junto(db: Session) -> None:
    unidade = _unidade(db)
    area = Area(unidade_id=unidade.id, nome="Praça de máquinas", codigo="PM")
    db.add(area)
    db.flush()
    db.add(
        Equipamento(
            area_id=area.id, tag="B-0001", descricao="Bomba", criticidade="alta"
        )
    )
    db.commit()

    db.delete(unidade)
    db.commit()

    assert db.scalars(select(Area)).all() == []
    assert db.scalars(select(Equipamento)).all() == []


def test_pt_com_trilha_de_auditoria_nao_pode_ser_apagada(db: Session) -> None:
    """Regra 4: apagar a PT apagaria a prova junto. O banco recusa."""
    pt = _pt_minima(db)
    db.add(
        AuditEvent(
            pt_id=pt.id,
            tipo_evento="pt.criada",
            estado_destino=pt.estado,
            hash_evento="a" * 64,
        )
    )
    db.commit()

    db.delete(pt)
    with pytest.raises(IntegrityError):
        db.commit()


def test_assinatura_e_unica_por_etapa_dentro_da_mesma_versao(db: Session) -> None:
    """A unicidade é por etapa, não por papel.

    O mesmo papel assina etapas diferentes de propósito — o executante inicia e encerra o
    trabalho. O que não pode é a mesma etapa da mesma versão ser assinada duas vezes.
    """
    pt = _pt_minima(db)
    dados = {
        "pt_id": pt.id,
        "usuario_id": pt.requisitante_id,
        "papel": PapelAssinatura.EXECUTANTE,
        "hash_documento": "b" * 64,
    }
    db.add(Assinatura(**dados, estado_destino=EstadoPT.EM_EXECUCAO, versao_pt=1))
    db.commit()

    # Mesmo papel, mesma versão, outra etapa: legítimo.
    db.add(Assinatura(**dados, estado_destino=EstadoPT.ENCERRADA, versao_pt=1))
    db.commit()

    # Mesma etapa numa versão nova: legítimo, o documento mudou.
    db.add(Assinatura(**dados, estado_destino=EstadoPT.EM_EXECUCAO, versao_pt=2))
    db.commit()

    db.add(Assinatura(**dados, estado_destino=EstadoPT.EM_EXECUCAO, versao_pt=2))
    with pytest.raises(IntegrityError):
        db.commit()


def test_seed_e_idempotente_e_deixa_uma_certificacao_vencida(db: Session) -> None:
    """O L4 precisa de um caso vencido em base para provar que a liberação é bloqueada."""
    semear(db)
    semear(db)

    assert len(db.scalars(select(Unidade)).all()) == 1
    assert len(db.scalars(select(Area)).all()) == 3
    assert len(db.scalars(select(Usuario)).all()) == 5
    assert len(db.scalars(select(Equipamento)).all()) == 2

    certificacoes = db.scalars(select(Certificacao)).all()
    assert len(certificacoes) == 4
    vencidas = [c for c in certificacoes if c.valida_ate < date.today()]
    assert len(vencidas) == 1
    assert vencidas[0].tipo == TipoCertificacao.NR_35


def test_seed_repara_usuario_criado_antes_da_credencial_existir(db: Session) -> None:
    """`_obter_ou_criar` não atualiza quem já existe — senha e lotação precisam ser reparadas.

    Sem isto, base semeada antes do L2 loga ninguém e, se logasse, emitiria PT nenhuma.
    """
    antigo = Usuario(
        matricula="10001",
        nome="Carlos Menezes",
        email="antigo@exemplo.com",
        empresa="Alpha Offshore",
        cargo="Encarregado",
        perfil=PerfilUsuario.REQUISITANTE,
    )
    db.add(antigo)
    db.commit()
    assert antigo.senha_hash == ""
    assert antigo.unidade_id is None

    semear(db)

    db.refresh(antigo)
    assert antigo.senha_hash.startswith("$argon2")
    assert antigo.unidade_id is not None
