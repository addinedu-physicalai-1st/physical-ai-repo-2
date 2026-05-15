"""SQLAlchemy DeclarativeBase — 모든 모델의 공통 베이스."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
