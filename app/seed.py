"""Dados de partida para desenvolvimento: `python -m app.seed`.

Rodar duas vezes não duplica nada — cada linha é procurada pela sua chave natural antes de
ser criada. As datas são relativas a hoje de propósito: seed com data fixa apodrece e passa a
mostrar tudo vencido depois de alguns meses.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Area, Certificacao, Equipamento, Unidade, Usuario
from app.models.enums import Criticidade, PerfilUsuario, TipoCertificacao, TipoUnidade

HOJE = date.today()


def _obter_ou_criar(db: Session, modelo: type, filtro: dict, **valores):
    """Devolve a linha que casa com `filtro`, ou cria uma com `filtro + valores`."""
    existente = db.scalars(select(modelo).filter_by(**filtro)).first()
    if existente is not None:
        return existente
    nova = modelo(**filtro, **valores)
    db.add(nova)
    db.flush()
    return nova


def semear(db: Session) -> None:
    """Cria 1 unidade, 3 áreas, 5 usuários, 2 equipamentos e 4 certificações."""
    unidade = _obter_ou_criar(
        db,
        Unidade,
        {"identificador_operacional": "FPSO-ALS-01"},
        nome="FPSO Alpha Sentinel",
        tipo=TipoUnidade.FPSO,
    )

    areas = {
        codigo: _obter_ou_criar(
            db, Area, {"unidade_id": unidade.id, "codigo": codigo}, nome=nome
        )
        for codigo, nome in (
            ("CV", "Convés principal"),
            ("PM", "Praça de máquinas"),
            ("CS", "Casario"),
        )
    }

    _obter_ou_criar(
        db,
        Equipamento,
        {"tag": "B-1201-A"},
        area_id=areas["PM"].id,
        descricao="Bomba de transferência de óleo",
        criticidade=Criticidade.ALTA,
    )
    _obter_ou_criar(
        db,
        Equipamento,
        {"tag": "TQ-3105"},
        area_id=areas["CV"].id,
        descricao="Tanque de lastro nº 5 — espaço confinado",
        criticidade=Criticidade.CRITICA,
    )

    pessoas = [
        ("10001", "Carlos Menezes", "carlos.menezes@exemplo.com", "Alpha Offshore",
         "Encarregado de manutenção", PerfilUsuario.REQUISITANTE),
        ("10002", "Rafael Souza", "rafael.souza@exemplo.com", "Contratada Meridiano",
         "Soldador", PerfilUsuario.EXECUTANTE),
        ("10003", "Juliana Prado", "juliana.prado@exemplo.com", "Alpha Offshore",
         "Técnica de segurança", PerfilUsuario.TECNICO_SEGURANCA),
        ("10004", "Marcos Ferreira", "marcos.ferreira@exemplo.com", "Alpha Offshore",
         "Supervisor de área", PerfilUsuario.AREA_RESPONSAVEL),
        ("10005", "Ana Beatriz Lima", "ana.lima@exemplo.com", "Alpha Offshore",
         "Coordenadora de operações", PerfilUsuario.COORDENADOR),
    ]
    usuarios = {
        matricula: _obter_ou_criar(
            db,
            Usuario,
            {"matricula": matricula},
            nome=nome,
            email=email,
            empresa=empresa,
            cargo=cargo,
            perfil=perfil,
        )
        for matricula, nome, email, empresa, cargo, perfil in pessoas
    }

    certificacoes = [
        # Rafael tem NR-34 em dia e a NR-35 **vencida** — é o caso que o L4 precisa barrar
        # na liberação de trabalho em altura.
        (usuarios["10002"], TipoCertificacao.NR_34, "34-8891", HOJE - timedelta(days=400),
         HOJE + timedelta(days=330)),
        (usuarios["10002"], TipoCertificacao.NR_35, "35-4477", HOJE - timedelta(days=760),
         HOJE - timedelta(days=45)),
        (usuarios["10003"], TipoCertificacao.NR_33, "33-2210", HOJE - timedelta(days=200),
         HOJE + timedelta(days=530)),
        (usuarios["10001"], TipoCertificacao.NR_10, "10-6654", HOJE - timedelta(days=120),
         HOJE + timedelta(days=610)),
    ]
    for usuario, tipo, numero, emitida_em, valida_ate in certificacoes:
        _obter_ou_criar(
            db,
            Certificacao,
            {"usuario_id": usuario.id, "tipo": tipo, "numero": numero},
            emitida_em=emitida_em,
            valida_ate=valida_ate,
        )

    db.commit()


def main() -> None:
    """Executa o seed contra o banco configurado em `AEGIS_DATABASE_URL`."""
    with SessionLocal() as db:
        semear(db)
    print("Seed aplicado: 1 unidade, 3 áreas, 5 usuários, 2 equipamentos, 4 certificações.")


if __name__ == "__main__":
    main()
