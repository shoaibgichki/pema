"""Add extended_facts_json to session_facts (v2 AI engine)

Revision ID: a1b2c3d4e5f6
Revises: 8456e3cd4241
Create Date: 2026-05-29 21:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '8456e3cd4241'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add extended_facts_json column to session_facts table.
    # Stores new v2 AI-captured context as a JSON blob:
    # medications, medical_history, allergies, lifestyle_factors.
    op.add_column(
        'session_facts',
        sa.Column('extended_facts_json', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('session_facts', 'extended_facts_json')
