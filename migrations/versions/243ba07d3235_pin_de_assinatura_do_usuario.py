"""pin de assinatura do usuario

Revision ID: 243ba07d3235
Revises: ccddf73c09f2
Create Date: 2026-08-11 19:41:01.820148

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '243ba07d3235'
down_revision: Union[str, Sequence[str], None] = 'ccddf73c09f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Acrescenta o PIN de assinatura, vazio para quem já existe.

    `server_default=""` é obrigatório aqui: a tabela já tem linhas, e o autogenerate omite o
    default numa coluna `NOT NULL` — o upgrade falharia em qualquer base povoada.

    Vazio não é um valor inventado, e é essa a diferença para a coluna `estado_destino` do L5,
    que entrou **sem** default de propósito. Ali não existia etapa plausível para atribuir a uma
    assinatura já gravada, e chutar uma seria falsificar registro. Aqui vazio é o estado real e
    verdadeiro: ninguém tinha PIN antes desta migration, e `pin_hash` vazio significa
    exatamente "esta pessoa ainda não assina" — que é como o sistema deve tratá-la até alguém
    lhe atribuir um PIN.
    """
    with op.batch_alter_table("usuario", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("pin_hash", sa.String(length=255), nullable=False, server_default="")
        )


def downgrade() -> None:
    """Remove o PIN de assinatura."""
    with op.batch_alter_table("usuario", schema=None) as batch_op:
        batch_op.drop_column("pin_hash")
