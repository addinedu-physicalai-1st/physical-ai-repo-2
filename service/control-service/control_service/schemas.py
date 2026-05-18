"""Pydantic 응답 모델 — portal-web src/types.ts 와 1:1 매칭."""
from datetime import date as DateType, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class ChildOut(BaseModel):
    id: int
    name: str
    birth_date: DateType
    class_name: str
    photo_url: str | None = None
    notes: str | None = None
    given_name: str | None = None


class ParentInfoOut(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    phone: str
    child_ids: list[int]


class ChildDetailOut(ChildOut):
    parents: list[ParentInfoOut]


class AttendanceRecordOut(BaseModel):
    child_id: int
    child_name: str
    check_in: datetime | None
    check_out: datetime | None


class MenuEntryOut(BaseModel):
    date: DateType
    items: list[str]


class ReportAttendanceDebugOut(BaseModel):
    """해당 일 `attendance` 테이블 기준 — 보고서 화면·API 디버그용."""

    has_check_in: bool
    has_check_out: bool
    check_in_kst: str | None = None
    check_out_kst: str | None = None


class ReportOut(BaseModel):
    id: int
    child_id: int
    date: DateType
    content: str
    created_at: datetime
    updated_at: datetime | None
    attendance_debug: ReportAttendanceDebugOut | None = None


class PhotoOut(BaseModel):
    id: int
    child_id: int | None
    url: str
    taken_at: datetime
    emotion: str | None
    emotion_score: float | None
    mode: str | None


class NaturalPhotoOut(BaseModel):
    photo_id: int
    url: str
    # 같은 session_id 로 이미 INSERT 된 행을 돌려준 경우 True (멱등).
    already: bool


class RegisterChildPayload(BaseModel):
    name: str
    birth_date: DateType
    class_name: str
    notes: str | None = None
    given_name: str | None = None


class ChildPatchPayload(BaseModel):
    notes: str | None = None
    given_name: str | None = None


class ParentPatchPayload(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None


class FaceRecognizeResult(BaseModel):
    matched: bool
    child_id: int | None = None
    child_name: str | None = None
    distance: float | None = None  # 0=동일, 큼=다름


# SR-PLAY-004 무궁화 진입 단계 — 한 프레임에 여러 명이 동시에 보일 때.
class FaceRecognizeSingleMatch(BaseModel):
    matched: bool
    child_id: int | None = None
    child_name: str | None = None
    distance: float | None = None
    # 같은 프레임 내 얼굴 위치 — 클라이언트가 등록 카드용 썸네일을 크롭할 때 사용.
    bbox: list[float] | None = None  # [x1, y1, x2, y2] in image pixels


class FaceRecognizeMultiResult(BaseModel):
    matches: list[FaceRecognizeSingleMatch]


class AttendanceCheckPayload(BaseModel):
    child_id: int
    type: Literal["IN", "OUT"]


class AttendanceCheckResult(BaseModel):
    child_id: int
    child_name: str
    type: str
    time: datetime
    already: bool  # 이미 같은 날 같은 type 기록이 있어 중복이면 True
    # 실물 팔로워 인사 모션 트리거 결과 (신규 기록일 때만 채움; 중복이면 None).
    # 값 예시: "fired" / "skipped:no_bridge" / "skipped:no_real_arm" / "skipped:routine_missing"
    arm_status: str | None = None


class RegisterParentPayload(BaseModel):
    name: str
    email: EmailStr
    phone: str
    child_id: int


class RegisterParentResponse(BaseModel):
    parent: ParentInfoOut
    initial_password: str


class ReportPatchPayload(BaseModel):
    content: str
