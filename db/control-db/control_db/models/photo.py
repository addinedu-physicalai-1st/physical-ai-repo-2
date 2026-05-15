"""Photo + PhotoSubject — 사진 메타 + N:N 등장 자녀 매핑."""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from control_db.models.base import Base


class Photo(Base):
    __tablename__ = "photo"
    __table_args__ = (
        UniqueConstraint("trigger_session_id", name="photo_trigger_session_id_uniq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 자연 촬영 시점에는 브라우저가 얼굴 식별을 안 하므로 nullable. SR-PHOTO-002 후처리에서 채움.
    child_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("child.id", ondelete="CASCADE"),
        nullable=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    emotion: Mapped[str | None] = mapped_column(String, nullable=True)
    emotion_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    mode: Mapped[str | None] = mapped_column(String, nullable=True)
    robot: Mapped[str | None] = mapped_column(String, nullable=True)
    # 모드 세션 멱등키 — 같은 session_id 로 두 번째 요청이 와도 중복 INSERT 안 됨.
    trigger_session_id: Mapped[str | None] = mapped_column(String, nullable=True)


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
