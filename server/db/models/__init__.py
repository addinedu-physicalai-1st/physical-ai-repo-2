"""모든 모델 re-export — Alembic autogenerate 가 import 1회로 metadata 수집."""
from server.db.models.base import Base
from server.db.models.user import User, AccessToken
from server.db.models.child import Child, ParentChild, ChildTeacher
from server.db.models.attendance import Attendance
from server.db.models.menu import Menu
from server.db.models.report import Report
from server.db.models.photo import Photo, PhotoSubject
from server.db.models.face_image import ChildFaceImage
from server.db.models.face_embedding import ChildFaceEmbedding

__all__ = [
    "Base",
    "User", "AccessToken",
    "Child", "ParentChild", "ChildTeacher",
    "Attendance",
    "Menu",
    "Report",
    "Photo", "PhotoSubject",
    "ChildFaceImage",
    "ChildFaceEmbedding",
]
