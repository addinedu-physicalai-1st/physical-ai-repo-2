"""교사 프로필 필드 — user 테이블에 6 컬럼 추가 (모두 nullable)

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("user", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("user", sa.Column("photo_url", sa.Text(), nullable=True))
    op.add_column("user", sa.Column("class_name", sa.String(length=32), nullable=True))
    op.add_column("user", sa.Column("hired_date", sa.Date(), nullable=True))
    op.add_column("user", sa.Column("emergency_contact", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "emergency_contact")
    op.drop_column("user", "hired_date")
    op.drop_column("user", "class_name")
    op.drop_column("user", "photo_url")
    op.drop_column("user", "address")
    op.drop_column("user", "birth_date")
