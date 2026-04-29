"""Attendance — 자녀별 등하원 기록."""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from server.db.models.base import Base


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        CheckConstraint("type IN ('IN','OUT')", name="attendance_type_check"),
        UniqueConstraint("child_id", "date", "type", name="attendance_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    child_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("child.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(String(3), nullable=False)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
