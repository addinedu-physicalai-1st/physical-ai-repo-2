"""ChildFaceEmbedding — InsightFace 임베딩 (pgvector)."""
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from server.db.models.base import Base


class ChildFaceEmbedding(Base):
    __tablename__ = "child_face_embedding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    child_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("child.id", ondelete="CASCADE"),
        nullable=False,
    )
    face_image_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("child_face_image.id", ondelete="CASCADE"),
        nullable=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
