"""O que cada tipo de trabalho exige.

Este arquivo é a tradução das normas para dados, e é de propósito legível por quem entende de
segurança e não de Python: mudar uma exigência aqui não deveria exigir tocar em lógica.

Nenhum destes valores pode vir de modelo de linguagem (regra 2). São tabelas fixas, versionadas
e cobertas por teste.
"""

from app.models.enums import EstadoPT, TipoAnexo, TipoCertificacao, TipoTrabalho

# Habilitação normativa exigida de cada executante, por tipo de trabalho.
CERTIFICACAO_EXIGIDA: dict[TipoTrabalho, TipoCertificacao] = {
    TipoTrabalho.ESPACO_CONFINADO: TipoCertificacao.NR_33,
    TipoTrabalho.TRABALHO_EM_ALTURA: TipoCertificacao.NR_35,
    TipoTrabalho.INTERVENCAO_ELETRICA: TipoCertificacao.NR_10,
    TipoTrabalho.TRABALHO_A_QUENTE: TipoCertificacao.NR_34,
    TipoTrabalho.INSPECAO_DRONE: TipoCertificacao.ANAC_RPAS,
    # Içamento não tem, entre as cinco normas do cadastro, uma habilitação individual
    # correspondente. Ausência aqui significa "nada a exigir", não "esqueci".
}

# Documentos que precisam estar anexados e válidos antes da liberação.
ANEXOS_EXIGIDOS: dict[TipoTrabalho, tuple[TipoAnexo, ...]] = {
    TipoTrabalho.TRABALHO_A_QUENTE: (TipoAnexo.APR,),
    TipoTrabalho.ESPACO_CONFINADO: (TipoAnexo.APR, TipoAnexo.ASO),
    TipoTrabalho.TRABALHO_EM_ALTURA: (TipoAnexo.APR, TipoAnexo.ASO),
    TipoTrabalho.INTERVENCAO_ELETRICA: (TipoAnexo.APR,),
    TipoTrabalho.ICAMENTO: (TipoAnexo.APR,),
    TipoTrabalho.INSPECAO_DRONE: (TipoAnexo.APR,),
}

# Janela máxima de uma PT, em horas. Um turno para a maioria; menos onde a exposição é o risco.
# Números de operação, não de física: ajustar aqui é o caminho previsto quando a unidade
# trabalha com outro regime de turno.
DURACAO_MAXIMA_HORAS: dict[TipoTrabalho, int] = {
    TipoTrabalho.ESPACO_CONFINADO: 8,
    TipoTrabalho.TRABALHO_EM_ALTURA: 8,
}
DURACAO_MAXIMA_PADRAO_HORAS = 12

# Pares que não podem coexistir na mesma área com janelas sobrepostas.
TRABALHOS_INCOMPATIVEIS: frozenset[frozenset[TipoTrabalho]] = frozenset(
    {
        # Fonte de ignição ao lado de atmosfera potencialmente inflamável, e o pessoal de
        # dentro do espaço sem rota de fuga rápida.
        frozenset({TipoTrabalho.TRABALHO_A_QUENTE, TipoTrabalho.ESPACO_CONFINADO}),
        # Faísca e material caindo sobre quem está suspenso.
        frozenset({TipoTrabalho.TRABALHO_A_QUENTE, TipoTrabalho.TRABALHO_EM_ALTURA}),
        # Carga suspensa passando por cima de quem trabalha em altura.
        frozenset({TipoTrabalho.ICAMENTO, TipoTrabalho.TRABALHO_EM_ALTURA}),
    }
)

# Estados em que a PT efetivamente ocupa a área. `APROVACAO` ainda não pôs ninguém no local.
ESTADOS_QUE_OCUPAM_A_AREA: frozenset[EstadoPT] = frozenset(
    {EstadoPT.LIBERACAO, EstadoPT.EM_EXECUCAO}
)

# Janela em que uma certificação prestes a vencer já merece aviso, sem bloquear.
DIAS_DE_AVISO_DE_VENCIMENTO = 30
