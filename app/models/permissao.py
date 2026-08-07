"""O documento: modelo de PT, a permissão em si, equipe, versões, anexos e assinaturas."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import JSON, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import EstadoPT, PapelAssinatura, TipoAnexo, TipoTrabalho
from app.models.pessoa import Usuario
from app.models.tipos import TimestampMixin, UTCDateTime, agora_utc, enum_col


class ModeloPT(TimestampMixin, Base):
    """Formulário aprovado para um tipo de trabalho.

    `campos` e `checklist` são JSON porque o formulário é dinâmico (L3): cada tipo de trabalho
    tem sua lista, e uma coluna por campo exigiria migration a cada revisão de modelo.
    """

    __tablename__ = "modelo_pt"
    __table_args__ = (
        UniqueConstraint("tipo_trabalho", "versao", name="uq_modelo_pt_tipo_trabalho_versao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo_trabalho: Mapped[TipoTrabalho] = mapped_column(enum_col(TipoTrabalho), nullable=False)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    versao: Mapped[int] = mapped_column(default=1, nullable=False)
    ativo: Mapped[bool] = mapped_column(default=True, nullable=False)
    campos: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    checklist: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)


class PermissaoTrabalho(TimestampMixin, Base):
    """A permissão de trabalho. Estado e versão mudam aqui; a história fica em `pt_versao`."""

    __tablename__ = "permissao_trabalho"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identidade estável entre dispositivos: o L12 cria PT offline, e id autoincrement
    # gerado em dois tablets colide na sincronização.
    uuid: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), unique=True, nullable=False
    )
    numero: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    tipo_trabalho: Mapped[TipoTrabalho] = mapped_column(enum_col(TipoTrabalho), nullable=False)
    estado: Mapped[EstadoPT] = mapped_column(
        enum_col(EstadoPT), default=EstadoPT.RASCUNHO, index=True, nullable=False
    )
    versao: Mapped[int] = mapped_column(default=1, nullable=False)

    modelo_pt_id: Mapped[int] = mapped_column(ForeignKey("modelo_pt.id"), nullable=False)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidade.id"), index=True, nullable=False)
    area_id: Mapped[int] = mapped_column(ForeignKey("area.id"), index=True, nullable=False)
    equipamento_id: Mapped[int | None] = mapped_column(ForeignKey("equipamento.id"))
    requisitante_id: Mapped[int] = mapped_column(
        ForeignKey("usuario.id"), index=True, nullable=False
    )

    descricao: Mapped[str] = mapped_column(Text, nullable=False)
    valida_de: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    valida_ate: Mapped[datetime] = mapped_column(UTCDateTime, index=True, nullable=False)
    perigos: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    controles: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    respostas: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    modelo: Mapped[ModeloPT] = relationship()
    requisitante: Mapped[Usuario] = relationship()
    equipe: Mapped[list["PTEquipe"]] = relationship(
        back_populates="pt", cascade="all, delete-orphan"
    )
    versoes: Mapped[list["PTVersao"]] = relationship(
        back_populates="pt", cascade="all, delete-orphan"
    )
    anexos: Mapped[list["Anexo"]] = relationship(back_populates="pt", cascade="all, delete-orphan")
    assinaturas: Mapped[list["Assinatura"]] = relationship(
        back_populates="pt", cascade="all, delete-orphan"
    )


class PTEquipe(Base):
    """Executante alocado a uma PT. É por aqui que o L4 alcança as certificações da equipe."""

    __tablename__ = "pt_equipe"
    __table_args__ = (UniqueConstraint("pt_id", "usuario_id", name="uq_pt_equipe_pt_usuario"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pt_id: Mapped[int] = mapped_column(
        ForeignKey("permissao_trabalho.id", ondelete="CASCADE"), index=True, nullable=False
    )
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), index=True, nullable=False)
    funcao: Mapped[str] = mapped_column(String(80), nullable=False)

    pt: Mapped[PermissaoTrabalho] = relationship(back_populates="equipe")
    usuario: Mapped[Usuario] = relationship()


class PTVersao(Base):
    """Retrato imutável da PT a cada revisão, com o diff campo a campo e o motivo."""

    __tablename__ = "pt_versao"
    __table_args__ = (UniqueConstraint("pt_id", "versao", name="uq_pt_versao_pt_versao"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pt_id: Mapped[int] = mapped_column(
        ForeignKey("permissao_trabalho.id", ondelete="CASCADE"), index=True, nullable=False
    )
    versao: Mapped[int] = mapped_column(nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    diff: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    autor_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        UTCDateTime, default=agora_utc, nullable=False
    )

    pt: Mapped[PermissaoTrabalho] = relationship(back_populates="versoes")


class Anexo(Base):
    """Documento acostado à PT. `hash_sha256` é o que prova que o arquivo não mudou depois."""

    __tablename__ = "anexo"

    id: Mapped[int] = mapped_column(primary_key=True)
    pt_id: Mapped[int] = mapped_column(
        ForeignKey("permissao_trabalho.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tipo: Mapped[TipoAnexo] = mapped_column(enum_col(TipoAnexo), nullable=False)
    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)
    caminho: Mapped[str] = mapped_column(String(500), nullable=False)
    hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    valido_ate: Mapped[date | None] = mapped_column(Date)
    enviado_por_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        UTCDateTime, default=agora_utc, nullable=False
    )

    pt: Mapped[PermissaoTrabalho] = relationship(back_populates="anexos")


class Assinatura(Base):
    """Assinatura de uma *etapa* do fluxo sobre uma *versão* da PT.

    A unicidade é por (pt, etapa, versão), e não por papel: o mesmo papel assina etapas
    diferentes legitimamente — o executante inicia e encerra o trabalho, o técnico de
    segurança analisa e depois suspende. Revisar o documento gera versão nova, e as
    assinaturas da versão anterior deixam de valer sem que nada seja apagado.
    """

    __tablename__ = "assinatura"
    __table_args__ = (
        UniqueConstraint(
            "pt_id", "estado_destino", "versao_pt", name="uq_assinatura_pt_etapa_versao"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pt_id: Mapped[int] = mapped_column(
        ForeignKey("permissao_trabalho.id", ondelete="CASCADE"), index=True, nullable=False
    )
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), index=True, nullable=False)
    papel: Mapped[PapelAssinatura] = mapped_column(enum_col(PapelAssinatura), nullable=False)
    # A etapa que esta assinatura autorizou — o estado para o qual a PT foi.
    estado_destino: Mapped[EstadoPT] = mapped_column(enum_col(EstadoPT), nullable=False)
    versao_pt: Mapped[int] = mapped_column(nullable=False)
    hash_documento: Mapped[str] = mapped_column(String(64), nullable=False)
    assinado_em: Mapped[datetime] = mapped_column(
        UTCDateTime, default=agora_utc, nullable=False
    )

    pt: Mapped[PermissaoTrabalho] = relationship(back_populates="assinaturas")
    usuario: Mapped[Usuario] = relationship()
