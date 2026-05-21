"""teacher_face_image + teacher_face_embedding 테이블 신설

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "teacher_face_image",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "teacher_id",
            UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("angle", sa.String(length=16), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "teacher_face_image_teacher_idx",
        "teacher_face_image",
        ["teacher_id"],
    )

    op.create_table(
        "teacher_face_embedding",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "teacher_id",
            UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "face_image_id",
            sa.Integer(),
            sa.ForeignKey("teacher_face_image.id", ondelete="CASCADE"),
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
        "teacher_face_embedding_teacher_idx",
        "teacher_face_embedding",
        ["teacher_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "teacher_face_embedding_teacher_idx", table_name="teacher_face_embedding"
    )
    op.drop_table("teacher_face_embedding")
    op.drop_index("teacher_face_image_teacher_idx", table_name="teacher_face_image")
    op.drop_table("teacher_face_image")
