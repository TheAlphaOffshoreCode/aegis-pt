"""Dados de partida para desenvolvimento: `python -m app.seed`.

Rodar duas vezes não duplica nada — cada linha é procurada pela sua chave natural antes de
ser criada. As datas são relativas a hoje de propósito: seed com data fixa apodrece e passa a
mostrar tudo vencido depois de alguns meses.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Area, Certificacao, Equipamento, ModeloPT, Unidade, Usuario
from app.models.enums import (
    Criticidade,
    PerfilUsuario,
    TipoCertificacao,
    TipoTrabalho,
    TipoUnidade,
)
from app.security.credenciais import gerar_hash

HOJE = date.today()

# Senha única de desenvolvimento. `main()` recusa rodar fora de desenvolvimento — seed com
# senha conhecida é exatamente como uma credencial de teste chega à produção.
SENHA_PADRAO = "aegis-dev-2026"

# PIN de assinatura, também só para desenvolvimento. Na operação real cada pessoa recebe o seu
# e ele nunca é igual ao de outra — um PIN compartilhado devolve o problema que a assinatura
# individual existe para resolver.
PIN_PADRAO = "2026"


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
    """Cria 1 unidade, 3 áreas, 5 usuários, 2 equipamentos, 4 certificações e 2 modelos."""
    # A guarda mora aqui, e não só em `main()`: quem importa `semear` também precisa esbarrar.
    if get_settings().environment != "development":
        raise RuntimeError("Seed é de desenvolvimento: ele cria contas com senha conhecida.")

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
            unidade_id=unidade.id,
            senha_hash=gerar_hash(SENHA_PADRAO),
            pin_hash=gerar_hash(PIN_PADRAO),
        )
        for matricula, nome, email, empresa, cargo, perfil in pessoas
    }
    # `_obter_ou_criar` só aplica valores na criação, então uma base semeada antes do L2 fica
    # sem senha e sem lotação — logando ninguém e, quando loga, sem escopo para emitir PT.
    #
    # Terceira vez que uma coluna nova de `usuario` precisa deste reparo (senha, lotação, agora
    # o PIN). O padrão já é conhecido: **toda coluna acrescentada a `usuario` depois da primeira
    # semeadura precisa de uma linha aqui**, ou uma base que atravessou loops fica em silêncio
    # com a forma antiga — e o sintoma aparece longe daqui, como "não consigo assinar".
    for usuario in usuarios.values():
        if not usuario.senha_hash:
            usuario.senha_hash = gerar_hash(SENHA_PADRAO)
        if not usuario.pin_hash:
            usuario.pin_hash = gerar_hash(PIN_PADRAO)
        # Quarta coluna a precisar do reparo. Aqui ele não é só simetria: quem exercitou
        # `POST /usuarios/{id}/pin` contra a base de desenvolvimento deixou o PIN marcado para
        # troca, e a partir daí `PIN_PADRAO` não assina mais nada. Ressemear é como se volta ao
        # estado documentado, então é aqui que a marca cai.
        if usuario.pin_precisa_troca:
            usuario.pin_precisa_troca = False
        if usuario.unidade_id is None:
            usuario.unidade_id = unidade.id

    _obter_ou_criar(
        db,
        ModeloPT,
        {"tipo_trabalho": TipoTrabalho.TRABALHO_A_QUENTE, "versao": 1},
        nome="PT de trabalho a quente",
        campos=[
            {"chave": "tipo_de_fogo", "rotulo": "Tipo de trabalho a quente", "tipo": "selecao",
             "obrigatorio": True, "opcoes": ["solda", "corte", "esmerilhamento"]},
            {"chave": "teste_de_gases_lie", "rotulo": "Teste de gases (% LIE)", "tipo": "numero",
             "obrigatorio": True},
            {"chave": "vigia_de_fogo", "rotulo": "Vigia de fogo designado", "tipo": "texto",
             "obrigatorio": True},
            {"chave": "area_isolada", "rotulo": "Área isolada e sinalizada", "tipo": "booleano",
             "obrigatorio": True},
            {"chave": "observacoes", "rotulo": "Observações", "tipo": "texto",
             "obrigatorio": False},
        ],
        checklist=[
            {"item": "Extintor posicionado a menos de 5 m da frente de serviço"},
            {"item": "Drenos e aberturas vedados no raio de 15 m"},
            {"item": "Detector de gás calibrado e com certificado válido"},
        ],
    )
    _obter_ou_criar(
        db,
        ModeloPT,
        {"tipo_trabalho": TipoTrabalho.TRABALHO_EM_ALTURA, "versao": 1},
        nome="PT de trabalho em altura",
        campos=[
            {"chave": "altura_metros", "rotulo": "Altura do serviço (m)", "tipo": "numero",
             "obrigatorio": True},
            {"chave": "ancoragem", "rotulo": "Tipo de ancoragem", "tipo": "selecao",
             "obrigatorio": True, "opcoes": ["linha_de_vida", "ponto_fixo", "andaime"]},
            {"chave": "plano_de_resgate", "rotulo": "Plano de resgate definido",
             "tipo": "booleano", "obrigatorio": True},
            {"chave": "data_inspecao_cinto", "rotulo": "Data da inspeção do cinto",
             "tipo": "data", "obrigatorio": True},
        ],
        checklist=[
            {"item": "Cinto tipo paraquedista com talabarte duplo"},
            {"item": "Área abaixo isolada contra queda de material"},
        ],
    )

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
    print(
        "Seed aplicado: 1 unidade, 3 áreas, 5 usuários, 2 equipamentos, 4 certificações "
        "e 2 modelos de PT.\n"
        f"Matrículas 10001 a 10005, senha '{SENHA_PADRAO}', "
        f"PIN de assinatura '{PIN_PADRAO}'."
    )


if __name__ == "__main__":
    main()
