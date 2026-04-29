"""child_face_embedding (pgvector)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "child_face_embedding",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "child_id",
            sa.Integer(),
            sa.ForeignKey("child.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "face_image_id",
            sa.Integer(),
            sa.ForeignKey("child_face_image.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "child_face_embedding_child_idx",
        "child_face_embedding",
        ["child_id"],
    )
    # IVFFlat 인덱스는 row 수가 적을 땐 의미가 없어 생략 (cosine 거리는 SeqScan)


def downgrade() -> None:
    op.drop_index("child_face_embedding_child_idx", table_name="child_face_embedding")
    op.drop_table("child_face_embedding")
    # extension 자체는 다른 곳에서 쓸 수도 있으므로 drop 안 함
