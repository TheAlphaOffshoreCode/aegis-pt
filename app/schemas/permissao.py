"""Schemas do modelo de PT, da permissão, equipe, versões, anexos e assinaturas.

`PTVersao`, `Assinatura` e o estado da PT não têm schema de escrita de propósito: são
produzidos pelo servidor, e aceitar qualquer um deles do cliente seria deixar o navegador
escolher em que estado a permissão está.
"""

from datetime import date, datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import EstadoPT, PapelAssinatura, TipoAnexo, TipoTrabalho
from app.schemas.auditoria import AuditEventRead
from app.schemas.base import ORMDatado, ORMSchema


class ModeloPTCreate(BaseModel):
    tipo_trabalho: TipoTrabalho
    nome: str = Field(min_length=1, max_length=120)
    versao: int = Field(default=1, ge=1)
    ativo: bool = True
    campos: list[dict] = Field(default_factory=list)
    checklist: list[dict] = Field(default_factory=list)


class ModeloPTRead(ORMDatado):
    id: int
    tipo_trabalho: TipoTrabalho
    nome: str
    versao: int
    ativo: bool
    campos: list[dict]
    checklist: list[dict]


class PTEquipeCreate(BaseModel):
    usuario_id: int
    funcao: str = Field(min_length=1, max_length=80)


class PTEquipeRead(ORMSchema):
    id: int
    pt_id: int
    usuario_id: int
    funcao: str


class _PermissaoTrabalhoEntrada(BaseModel):
    """Campos que o cliente pode informar. Número, uuid, estado e versão nunca estão aqui."""

    tipo_trabalho: TipoTrabalho
    modelo_pt_id: int
    area_id: int
    equipamento_id: int | None = None
    descricao: str = Field(min_length=1)
    valida_de: datetime
    valida_ate: datetime
    perigos: list[dict] = Field(default_factory=list)
    controles: list[dict] = Field(default_factory=list)
    respostas: dict = Field(default_factory=dict)
    equipe: list[PTEquipeCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _janela_valida(self) -> "_PermissaoTrabalhoEntrada":
        """Janela invertida deixaria a PT vencida no instante em que nasce."""
        if self.valida_ate <= self.valida_de:
            raise ValueError("valida_ate precisa ser posterior a valida_de")
        return self


class PermissaoTrabalhoCreate(_PermissaoTrabalhoEntrada):
    unidade_id: int


class PermissaoTrabalhoUpdate(_PermissaoTrabalhoEntrada):
    """Correção de rascunho. A unidade não muda: mudá-la seria emitir outra PT.

    `visto_em` é o `atualizado_em` que o cliente leu antes de editar, devolvido como veio. É o
    que impede a edição de sobrescrever em silêncio uma alteração que chegou no meio — o caso
    que o L12 precisa cobrir, porque um tablet offshore edita offline e envia meia hora depois.

    Obrigatório de propósito: um cliente que não diz o que viu não tem como afirmar que não
    atropelou ninguém.
    """

    visto_em: datetime

    @field_validator("visto_em")
    @classmethod
    def _em_utc(cls, valor: datetime) -> datetime:
        """Sem fuso significa UTC, igual ao que a borda do banco faz com toda data.

        Sem isto, um cliente que serialize sem offset compara ingênuo com aware, nunca
        coincide e leva `409` em toda edição — falha fechada, mas por um motivo que não é o
        que a mensagem diz.
        """
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


class PermissaoTrabalhoRead(ORMDatado):
    id: int
    uuid: str
    numero: str
    tipo_trabalho: TipoTrabalho
    estado: EstadoPT
    versao: int
    modelo_pt_id: int
    unidade_id: int
    area_id: int
    equipamento_id: int | None
    requisitante_id: int
    descricao: str
    valida_de: datetime
    valida_ate: datetime
    perigos: list[dict]
    controles: list[dict]
    respostas: dict


class PTVersaoRead(ORMSchema):
    id: int
    pt_id: int
    versao: int
    snapshot: dict
    diff: dict
    autor_id: int
    motivo: str
    criado_em: datetime


class AnexoRead(ORMSchema):
    id: int
    pt_id: int
    tipo: TipoAnexo
    nome_arquivo: str
    hash_sha256: str
    valido_ate: date | None
    enviado_por_id: int
    criado_em: datetime


class FiltroPT(BaseModel):
    """Filtros da busca, usados como parâmetros de consulta.

    Todos combinam entre si com `E`. O escopo do usuário não está aqui de propósito: ele não é
    filtro que alguém escolhe, é restrição aplicada sempre.
    """

    numero: str | None = Field(default=None, max_length=20)
    texto: str | None = Field(default=None, max_length=200, description="Busca na descrição")
    estado: EstadoPT | None = None
    tipo_trabalho: TipoTrabalho | None = None
    unidade_id: int | None = None
    area_id: int | None = None
    equipamento_id: int | None = None
    requisitante_id: int | None = None
    vigentes_em: datetime | None = None
    inicio_apos: datetime | None = None
    inicio_antes: datetime | None = None

    limite: int = Field(default=50, ge=1, le=200)
    deslocamento: int = Field(default=0, ge=0)


class PaginaDePTs(BaseModel):
    """Uma página de resultados. `total` é a contagem sem o recorte, para a tela paginar."""

    total: int
    limite: int
    deslocamento: int
    itens: list["PermissaoTrabalhoRead"]


class PendenciaRead(BaseModel):
    """Veredito do motor de regras. `codigo` e `campo` são o que a tela usa para marcar o erro."""

    codigo: str
    severidade: str
    mensagem: str
    campo: str | None
    responsavel: str | None


class AvaliacaoRead(BaseModel):
    """Resultado da avaliação. `liberavel` é conclusão do motor, nunca opinião de modelo."""

    pt_id: int
    numero: str
    liberavel: bool
    pendencias: list[PendenciaRead]


class DossieRead(BaseModel):
    """A PT e tudo o que aconteceu com ela.

    `trilha_integra` vem junto de propósito: histórico que não diz se foi adulterado não serve
    como prova, e é exatamente como prova que este documento é pedido.
    """

    model_config = ConfigDict(from_attributes=True)

    pt: "PermissaoTrabalhoRead"
    versoes: list["PTVersaoRead"]
    assinaturas: list["AssinaturaRead"]
    anexos: list["AnexoRead"]
    equipe: list["PTEquipeRead"]
    eventos: list[AuditEventRead]
    trilha_integra: bool
    quebras: list[dict]
    pendencias: list[PendenciaRead]


class TransicaoRequest(BaseModel):
    """Pedido de mudança de estado. O destino é declarado; o caminho, a máquina é que conhece.

    `visto_em` é o `atualizado_em` que o cliente leu antes de assinar. Opcional, ao contrário
    do que acontece na edição, e a diferença é deliberada: aqui ele não impede sobrescrita —
    impede **assinar um documento que mudou depois de você lê-lo**. Cliente antigo que não o
    envia continua funcionando; o que o envia ganha a conferência.
    """

    destino: EstadoPT
    visto_em: datetime | None = None
    motivo: str | None = Field(default=None, max_length=2000)
    # O navegador informa; o servidor registra como veio, sem inventar quando falta.
    geolocalizacao: str | None = Field(default=None, max_length=80)

    @field_validator("visto_em")
    @classmethod
    def _em_utc(cls, valor: datetime | None) -> datetime | None:
        """Mesma normalização da edição: sem fuso significa UTC."""
        if valor is None or valor.tzinfo:
            return valor
        return valor.replace(tzinfo=timezone.utc)


class TransicaoDisponivel(BaseModel):
    """Um passo possível a partir do estado atual, e se este usuário pode dá-lo."""

    destino: EstadoPT
    papel: PapelAssinatura
    assina: bool
    permitida: bool


class AssinaturaRead(ORMSchema):
    id: int
    pt_id: int
    usuario_id: int
    papel: PapelAssinatura
    estado_destino: EstadoPT
    versao_pt: int
    hash_documento: str
    assinado_em: datetime
