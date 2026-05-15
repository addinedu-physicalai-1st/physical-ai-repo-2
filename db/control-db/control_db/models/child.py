"""Child + 매핑 (parent_child, child_teacher)."""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from control_db.models.base import Base


class Child(Base):
    __tablename__ = "child"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    class_name: Mapped[str] = mapped_column(String, nullable=False)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    given_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ParentChild(Base):
    __tablename__ = "parent_child"

    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    child_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("child.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ChildTeacher(Base):
    __tablename__ = "child_teacher"

    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    child_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("child.id", ondelete="CASCADE"),
        primary_key=True,
    )
