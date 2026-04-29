"""Menu — day-of-month (1~31) 기준 점심메뉴."""
from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from server.db.models.base import Base


class Menu(Base):
    __tablename__ = "menu"
    __table_args__ = (
        CheckConstraint("day BETWEEN 1 AND 31", name="menu_day_check"),
    )

    day: Mapped[int] = mapped_column(Integer, primary_key=True)
    items: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # bge-m3 임베딩 (1024 차원). seed 시 채움 — chat RAG 가 day-of-month 와 무관한
    # 의미 검색 ("딸기 언제 나와?", "함박스테이크 먹는 날") 에 사용.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
