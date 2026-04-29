"""Photo + PhotoSubject — 사진 메타 + N:N 등장 자녀 매핑."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.db.models.base import Base


class Photo(Base):
    __tablename__ = "photo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    child_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("child.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    emotion: Mapped[str | None] = mapped_column(String, nullable=True)
    mode: Mapped[str | None] = mapped_column(String, nullable=True)


class PhotoSubject(Base):
    __tablename__ = "photo_subject"

    photo_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("photo.id", ondelete="CASCADE"),
        primary_key=True,
    )
    child_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("child.id", ondelete="CASCADE"),
        primary_key=True,
    )
