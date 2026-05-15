"""모든 모델 re-export — Alembic autogenerate 가 import 1회로 metadata 수집."""
from control_db.models.base import Base
from control_db.models.user import User, AccessToken
from control_db.models.child import Child, ParentChild, ChildTeacher
from control_db.models.attendance import Attendance
from control_db.models.menu import Menu
from control_db.models.report import Report
from control_db.models.photo import Photo, PhotoSubject
from control_db.models.face_image import ChildFaceImage
from control_db.models.face_embedding import ChildFaceEmbedding

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
