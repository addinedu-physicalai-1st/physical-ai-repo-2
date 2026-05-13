"""child.given_name — 보고서·호출용 이름(비우면 성 제거 추정)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("child", sa.Column("given_name", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("child", "given_name")
