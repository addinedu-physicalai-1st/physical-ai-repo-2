# Teacher Profile + Face Registration — 설계서

- 작성일: 2026-05-20
- 대상 서비스: `service/control-service/`, `service/web-service/portal-web/`, `db/control-db/`
- 목적: 교사 본인의 프로필 정보 (인적사항 + 다각도 얼굴) 를 Portal Web 에서 등록·수정할 수 있게 하고, GogoPing 추종 시 `SR-CAR-001 추종 대상 확인` 매칭의 대조 데이터로 활용한다.

## 1. 배경

현재 [`User` 테이블](../../../db/control-db/control_db/models/user.py) 에는 `email`, `name`, `phone` 만 있어 교사 식별 외 인적사항이 부재하고, 얼굴 데이터는 [`ChildFaceEmbedding`](../../../db/control-db/control_db/models/face_embedding.py) 으로 **자녀만** 저장된다. 따라서:

- `SR-CAR-001 추종 대상 확인` 의 "등록 교사와 매칭" 단계가 비교 대상 임베딩이 없어 구현 불가.
- 교사 본인이 자신의 정보를 조회·수정할 수 있는 UI 자체가 없다 — DB seed 또는 admin 수단으로만 입력된다.
- 다른 교사의 정보 (담당 반·연락처) 를 시스템 내에서 확인할 수단도 없다.

## 2. 목표 / 비-목표

**목표**

- 교사 프로필 페이지 (`/teacher/profile`) 를 신설해 본인 정보 조회·수정·얼굴 등록을 한 화면에서 처리한다.
- 교사 목록 페이지 (`/teacher/colleagues`) 를 신설해 모든 교사의 인적사항을 조회할 수 있게 한다.
- 자녀 얼굴 등록과 대칭되는 `teacher_face_image` + `teacher_face_embedding` 스키마를 만들고 InsightFace 임베딩 파이프라인 ([`face_recognition.py`](../../../service/control-service/control_service/face_recognition.py)) 을 재사용한다.
- 교사 얼굴 매칭 REST API 를 추가해 추후 GogoPing 노트북에서 호출 가능한 형태로 둔다 (`SR-CAR-001` 구현 시 사용).

**비-목표 (YAGNI)**

- GogoPing ROS2 노드 측 얼굴 매칭 로직 (`SR-CAR-001` 의 실제 추종 진입). 이번 작업은 Portal/Control 까지만; ROS 노드 통합은 별도 plan.
- Anti-spoofing (`SR-REG-010`). 자녀 얼굴 등록과 동일 정책을 적용하되 별도 구현은 안 함 — 자녀 쪽 도입 시 함께 적용.
- Admin UI (PyQt5) 의 교사 관리 화면. Portal Web 만 다룬다.
- 교사 가입 (self sign-up). 계정 자체는 seed/별도 admin 으로 들어가고, 본인이 "프로필" 만 채운다.

## 3. 아키텍처

### 3.1 DB 스키마 변경

#### 3.1.1 `user` 테이블 — 컬럼 추가 (모두 nullable)

| 컬럼 | 타입 | 의미 |
|---|---|---|
| `birth_date` | `Date` | 생년월일 — 나이는 화면에서 계산 |
| `address` | `Text` | 주소 |
| `photo_url` | `Text` | 일반 프로필 사진 URL (단일 정면 사진, 표시용) |
| `class_name` | `String(32)` | 담당 반 (예: `햇님반`) — 학부모는 NULL |
| `hired_date` | `Date` | 입사일 — 학부모는 NULL |
| `emergency_contact` | `String(64)` | 비상연락처 |

학부모도 같은 `user` 테이블이지만 학부모 row 에서는 `class_name`, `hired_date` 가 NULL 로 남는다. role 별 검증은 application 레벨 (Pydantic) 에서 한다.

#### 3.1.2 `teacher_face_image` 테이블 — NEW

자녀 [`ChildFaceImage`](../../../db/control-db/control_db/models/face_image.py) 와 대칭.

```python
class TeacherFaceImage(Base):
    __tablename__ = "teacher_face_image"
    id: int (PK, autoincrement)
    teacher_id: UUID (FK user.id ON DELETE CASCADE, indexed)
    file_path: Text (NOT NULL)             # 디스크 절대 경로
    angle: String(16) (nullable)           # "front", "left", "right", "up", "down"
    uploaded_at: timestamptz (default now)
```

저장 위치: `server/storage/teacher_faces/{teacher_uuid}/{idx}.jpg` (`settings.photos_dir` 와 동일 마운트 정책).

#### 3.1.3 `teacher_face_embedding` 테이블 — NEW

자녀 [`ChildFaceEmbedding`](../../../db/control-db/control_db/models/face_embedding.py) 와 대칭.

```python
class TeacherFaceEmbedding(Base):
    __tablename__ = "teacher_face_embedding"
    id: int (PK, autoincrement)
    teacher_id: UUID (FK user.id ON DELETE CASCADE, indexed)
    face_image_id: int (FK teacher_face_image.id ON DELETE CASCADE, nullable)
    embedding: Vector(512) (NOT NULL)      # pgvector — InsightFace 출력
    created_at: timestamptz (default now)
```

매칭은 `embedding <=> $target` (cosine distance) 로 수행. teacher 당 N 개 (각도별 5개 권장) 저장한다.

### 3.2 API 인터페이스

전부 `service/control-service/control_service/routers/teachers.py` 신설 + `main.py` 에 등록.

| Method · Path | Role | 동작 |
|---|---|---|
| `GET /api/teachers/me` | teacher | 본인 프로필 (인적사항 + 얼굴 등록 여부) |
| `PATCH /api/teachers/me` | teacher | 본인 프로필 수정 (`name`, `phone`, `birth_date`, `address`, `class_name`, `hired_date`, `emergency_contact`) |
| `POST /api/teachers/me/profile-photo` | teacher | 단일 정면 사진 업로드 → `photo_url` 갱신 |
| `POST /api/teachers/me/face-images` | teacher | 다각도 얼굴 5장 업로드 → InsightFace 임베딩 추출 → `teacher_face_image` + `teacher_face_embedding` INSERT (기존 row 는 DELETE 후 재삽입) |
| `GET /api/teachers/me/face-status` | teacher | `{ registered: bool, image_count: int, updated_at: ISO }` |
| `GET /api/teachers/` | teacher | **모든 교사** 목록 — `[{ id, name, class_name, phone, emergency_contact, photo_url, hired_date }]` |
| `POST /api/teachers/match-face` | teacher (또는 device token) | body: `{ image: multipart }` → 가장 가까운 교사 1명 또는 null |

응답 schema (예시):

```python
class TeacherProfileOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    phone: str | None
    birth_date: date | None
    address: str | None
    class_name: str | None
    hired_date: date | None
    emergency_contact: str | None
    photo_url: str | None
    face_registered: bool         # teacher_face_embedding row 존재
    face_image_count: int

class TeacherUpdatePayload(BaseModel):
    name: str | None = None
    phone: str | None = None
    birth_date: date | None = None
    address: str | None = None
    class_name: str | None = None
    hired_date: date | None = None
    emergency_contact: str | None = None

class TeacherMatchOut(BaseModel):
    teacher_id: UUID | None
    name: str | None
    distance: float | None         # cosine distance (0 = 동일)
    threshold: float               # 매칭 임계값 (현재 0.45 — 자녀와 동일)
    matched: bool
```

매칭 임계값은 [`face_recognition.py`](../../../service/control-service/control_service/face_recognition.py) 의 자녀용 상수를 재사용하거나, 동일 모듈에 `TEACHER_MATCH_THRESHOLD = 0.45` 로 둔다 (이번 작업에서는 추후 튜닝 가능하도록 상수로만 박는다).

### 3.3 UI 흐름 — Portal Web

#### 3.3.1 라우트 추가

[`router/index.ts`](../../../service/web-service/portal-web/src/router/index.ts) 의 `/teacher` children 에 두 라우트 추가:

```
/teacher/profile      → Profile.vue       (본인 정보 — 조회·수정·얼굴 등록)
/teacher/colleagues   → Colleagues.vue    (모든 교사 조회 — 읽기 전용)
```

#### 3.3.2 Profile.vue 화면 구성

```
┌─ 내 정보 ────────────────────────────────┐
│ 프로필 사진      [표시 + 변경 버튼]      │
│                                          │
│ 이메일           teacher@test.com (RO)   │
│ 이름             [노영주        ]         │
│ 생년월일         [1985-03-12   ]          │
│ 전화번호         [010-...      ]          │
│ 주소             [서울시 ...   ]          │
│ 담당 반          [햇님반       ]          │
│ 입사일           [2024-03-02   ]          │
│ 비상연락처       [010-...      ]          │
│                  [저장]                  │
├──────────────────────────────────────────┤
│ GogoPing 추종용 얼굴 등록                │
│ • 미등록 — [얼굴 캡처 시작]              │
│   또는                                    │
│ • 등록됨 (5장 · 2026-05-20) [재캡처]    │
│                                          │
│   → 클릭 시 <FaceCapture> 모달 (5각도)  │
└──────────────────────────────────────────┘
```

`<FaceCapture>` 는 자녀 등록과 동일한 [컴포넌트](../../../service/web-service/portal-web/src/components/teacher/FaceCapture.vue) 를 그대로 사용 — emit `complete(images: Blob[])` 을 받아 `/api/teachers/me/face-images` 로 POST.

#### 3.3.3 Colleagues.vue 화면 구성

읽기 전용 카드 그리드. 각 카드: 사진 / 이름 / 담당 반 / 전화 / 비상연락처. 검색·필터는 MVP 범위 외. 본인 카드도 함께 표시되며 클릭 시 `/teacher/profile` 로 이동.

#### 3.3.4 네비게이션

[`TeacherLayout.vue`](../../../service/web-service/portal-web/src/layouts/TeacherLayout.vue) 의 사이드/탑 네비에 `내 정보` · `교사 목록` 추가. 기존 `대시보드 / 어린이 / 메뉴 / 보고서` 와 동등 레벨.

## 4. 보안·권한

- 모든 `/api/teachers/*` 는 `require_teacher` (fastapi-users 세션 + role check) 통과 필수.
- `PATCH /api/teachers/me`, `POST /api/teachers/me/*` 는 본인 id 만 — request body 에 `teacher_id` 같은 필드 두지 않고 `current_user.id` 만 사용.
- `GET /api/teachers/` 는 본인이 아닌 다른 교사도 반환하지만 `email`, `address`, `birth_date` 같은 민감 필드는 제외. 직장 동료 명함 정도 (`name`, `class_name`, `phone`, `emergency_contact`, `photo_url`, `hired_date`).
- `POST /api/teachers/match-face` 는 추후 GogoPing 노트북에서 호출하므로 device token 도 허용해야 한다 — `Depends(require_teacher_or_device_token)` 헬퍼를 추가하거나, 본 plan 에서는 일단 `require_teacher` 만 두고 device token 허용은 GogoPing 통합 plan 에서 처리.

## 5. 마이그레이션 전략

- Alembic 새 revision **두 개**:
  1. `0007_teacher_profile_fields.py` — `user` 컬럼 6개 ADD COLUMN (전부 nullable, 기본값 NULL)
  2. `0008_teacher_face.py` — `teacher_face_image`, `teacher_face_embedding` CREATE TABLE
- 기존 row (teacher@test.com, 학부모 4명) 에 영향 없음 — 모두 NULL.
- 다운그레이드는 ADD COLUMN → DROP COLUMN, CREATE TABLE → DROP TABLE 으로 대칭 작성.
- seed 스크립트 ([`seed.py`](../../../db/control-db/control_db/seed.py)) 의 `seed_teacher` 는 기본 인적사항 (담당 반 `햇님반`, 입사일 `2024-03-02` 등) 을 채우도록 갱신 — UI 검증 편의.

## 6. SR 매핑

이 작업으로 추가/충족되는 시스템 요구사항:

| SR | Name | 충족 방식 |
|---|---|---|
| `SR-REG-011` (신설) | 교사 프로필 입력·수정 | `PATCH /api/teachers/me` + Profile.vue |
| `SR-REG-012` (신설) | 교사 얼굴 등록 | `POST /api/teachers/me/face-images` + FaceCapture |
| `SR-OPS-019` (신설) | 교사 정보 보기 (동료) | `GET /api/teachers/` + Colleagues.vue |
| `SR-CAR-009` (신설) | 교사 얼굴 매칭 API | `POST /api/teachers/match-face` (GogoPing 통합은 별도 plan) |

`SR-CAR-001 추종 대상 확인` 자체는 GogoPing 노트북 ROS 노드 통합이 남아 있어 이번 작업으로는 완료되지 않지만, 매칭 API 가 준비되므로 다음 단계 plan 에서 호출 지점만 연결하면 된다.

## 7. 테스트 전략

- **pytest** (`service/control-service/control_service/tests/test_teachers.py`)
  - GET /me 본인 프로필 반환 (역할 = teacher)
  - PATCH /me 부분 업데이트 + 본인이 아닌 변경 시도 차단
  - POST /me/face-images 5장 업로드 → embedding row 5개 생성, 재업로드 시 기존 row 삭제 후 재삽입
  - GET /me/face-status registered=true/false 경로
  - GET / 다른 교사 반환 + 민감 필드 마스킹
  - POST /match-face 등록된 교사 사진 → matched=true, 미등록 얼굴 → matched=false
- **vitest** (`service/web-service/portal-web/tests/components/Profile.test.ts`)
  - 폼 렌더링, save 호출 시 PATCH 발생
  - face-status registered=false 일 때 "얼굴 캡처 시작" 버튼 노출
  - FaceCapture complete 이벤트 → upload 호출 + 성공 시 UI 갱신

## 8. 비-목표 재확인

- GogoPing ROS 노드 통합 (matched teacher → 추종 시작) → 별도 plan.
- Anti-spoofing → `SR-REG-010` 이 자녀까지 포함해 별도 처리.
- 다른 교사의 정보 *수정* 권한 (admin 화면) → 본인만 수정.
- 교사 가입 (self sign-up) 화면 → seed/admin 으로 발급.
