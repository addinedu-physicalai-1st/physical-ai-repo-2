"""TeacherFaceEmbedding — InsightFace 임베딩 (pgvector, 교사 추종 매칭용)."""
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from control_db.models.base import Base


class TeacherFaceEmbedding(Base):
    __tablename__ = "teacher_face_embedding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    face_image_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("teacher_face_image.id", ondelete="CASCADE"),
        nullable=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
