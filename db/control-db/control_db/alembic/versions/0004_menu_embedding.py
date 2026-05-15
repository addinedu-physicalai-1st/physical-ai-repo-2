"""menu.embedding (pgvector — bge-m3, 1024 차원)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0003 에서 이미 enable. idempotent 하니 한 번 더 호출해도 안전.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # bge-m3 는 1024 차원 출력. nullable 로 추가 — seed 시 채움.
    op.add_column("menu", sa.Column("embedding", Vector(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("menu", "embedding")
