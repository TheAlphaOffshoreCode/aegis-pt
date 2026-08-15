"""troca obrigatoria do pin atribuido

Revision ID: be61b122016b
Revises: 243ba07d3235
Create Date: 2026-08-14 19:05:45.095327

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be61b122016b'
down_revision: Union[str, Sequence[str], None] = '243ba07d3235'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Marca se o PIN veio de terceiro e ainda não foi trocado.

    `server_default` é obrigatório e o autogenerate o omitiu, como sempre omite numa coluna
    `NOT NULL`: a tabela já tem linhas, e sem ele o upgrade falha em qualquer base povoada.

    **Falso para quem já existe**, e a escolha merece o parágrafo. Verdadeiro seria o valor
    paranoico — todo PIN anterior a esta migration foi, a rigor, atribuído por outra pessoa (o
    seed) — mas trancaria a assinatura de todo mundo numa base existente até cada um trocar, e
    o único lugar onde isso acontece hoje é desenvolvimento, cujo PIN compartilhado já é
    conhecido e já está documentado como de desenvolvimento.

    A coluna descreve uma entrega que este código passou a registrar; ela não sabe contar o
    passado, e fingir que sabe cobraria o preço de uma frota travada por uma inferência. Numa
    implantação real o caminho é o inverso e é o correto: ninguém tem PIN, a coordenação
    atribui, e cada atribuição já nasce marcada.
    """
    with op.batch_alter_table("usuario", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "pin_precisa_troca",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    """Remove a marca de troca obrigatória."""
    with op.batch_alter_table("usuario", schema=None) as batch_op:
        batch_op.drop_column("pin_precisa_troca")
