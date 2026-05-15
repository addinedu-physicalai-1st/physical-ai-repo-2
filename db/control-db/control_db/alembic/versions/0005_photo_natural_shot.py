"""photo — 자연 촬영 필드 추가 + child_id nullable

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-12

OX 퀴즈 자연 촬영용. 브라우저에서 얼굴 식별을 안 하니 capture 시점에는 child_id 가
미정 (SR-PHOTO-002 후처리에서 채움) — child_id NOT NULL 제약 완화. 동일 세션 중복
INSERT 방지를 위해 trigger_session_id UNIQUE 컬럼 추가.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("photo", "child_id", nullable=True)
    op.add_column(
        "photo",
        sa.Column("emotion_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "photo",
        sa.Column("robot", sa.String(), nullable=True),
    )
    op.add_column(
        "photo",
        sa.Column("trigger_session_id", sa.String(), nullable=True),
    )
    op.create_unique_constraint(
        "photo_trigger_session_id_uniq",
        "photo",
        ["trigger_session_id"],
    )


def downgrade() -> None:
    op.drop_constraint("photo_trigger_session_id_uniq", "photo", type_="unique")
    op.drop_column("photo", "trigger_session_id")
    op.drop_column("photo", "robot")
    op.drop_column("photo", "emotion_score")
    op.alter_column("photo", "child_id", nullable=False)
