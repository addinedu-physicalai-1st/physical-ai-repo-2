# Dependencies Audit

**최종 갱신:** 2026-05-28
**점검 범위:** `controller/*` + `service/*` 의 모든 `.py` 파일의 `import` 문 → 의존성 매니페스트 매핑.

## 의존성 출처 3 곳 (어디에 무엇이 명시되어 있나)

| 출처 | 범위 | CLAUDE.md 가이드 |
|---|---|---|
| 루트 [pyproject.toml](../pyproject.toml) | conda env (서비스 / Admin UI / 일부 ROS 노드 import 도 포함) | "의존성은 루트 pyproject.toml 하나로 통합 관리" |
| `apt install ros-jazzy-…` | ROS 2 Jazzy 기본 패키지 (rclpy / 메시지 / tf2) | "ROS Python 노드는 system python 으로 실행" |
| `sudo pip --break-system-packages …` | ROS 노드가 system python 에서 import 하는 비표준 패키지 (`/opt/ros/jazzy/lib/python3.12/site-packages` 의 외부) | "ROS 노드가 import 하는 비표준 패키지는 system python 에도 깔아둔다" |

ROS 노드 (perception, camera, follow, modes 등) 는 `colcon build` 후 install 의 entry-point 스크립트가 `#!/usr/bin/python3` 로 fix → **system python** 으로 실행. 그래서 `ultralytics`, `torchreid` 같은 무거운 패키지가 system 측 pip 으로도 별도 설치되어야 한다.

## 실제 코드 사용 vs 명시 위치 매트릭스

✓ = pyproject.toml 에 있음. ⚪ = system pip / apt (ROS 노드용). ❌ = 누락.

| import | 사용 패키지 | pip 이름 | pyproject.toml | system pip | apt | 상태 |
|---|---|---|---|---|---|---|
| `ultralytics` | perception | `ultralytics>=8.4,<9` | ✓ | ✓ (CLAUDE.md) | | OK |
| `lap` | perception (ByteTrack) | `lap>=0.5.12` | ✓ | ✓ | | OK |
| `torchreid` | perception (ReID) | `torchreid` | ❌ | ✓ | | **누락 — pyproject.toml** |
| `torch` | torchreid 의 dep + lerobot transitive | `torch` | ❌ (transitive) | (torchreid 와 함께) | | transitive 의존 — 명시 권장 |
| `insightface` | perception, ai-service | `insightface>=0.7` | ✓ | | | OK |
| `onnxruntime` | insightface backend | `onnxruntime>=1.18` | ✓ | | | OK |
| `cv2` | perception, camera | `opencv-python-headless>=4.10` | ✓ | | | OK |
| `numpy` | 전반 | `numpy` | ❌ (transitive) | | | transitive 의존 — 명시 권장 |
| `PIL` | noriarm framework | `pillow` | ❌ (transitive) | | | transitive 의존 — 명시 권장 |
| `pyrealsense2` | camera (D435) | `pyrealsense2>=2.55` | ✓ | ✓ | | OK |
| `aiortc` | camera, control-service (WebRTC) | `aiortc>=1.9` | ✓ | ✓ | | OK |
| `av` | aiortc / audio | `av>=12` | ✓ | ✓ | | OK |
| `websockets` | camera, control-service | `websockets>=13` | ✓ | ✓ | | OK |
| `yaml` | manifest, navigation | `pyyaml>=6.0` | ✓ | | | OK |
| `serial` | camera_pan (Arduino) | `pyserial>=3.5` | ✓ | (apt: `python3-serial`) | ✓ | OK |
| `py_trees` | modes (BT core) | `py-trees>=2.2,<2.3` | ✓ | | | OK |
| `py_trees_ros` | modes (BT ROS bindings) | (워크스페이스 벤더링 `controller/gogoping-controller/src/py_trees_ros/`) | — | — | — | workspace 안 |
| `transitions` | modes (FSM) | `transitions>=0.9` | ✓ | | | OK |
| `fastapi` | service | `fastapi>=0.115` | ✓ | | | OK |
| `uvicorn` | service | `uvicorn[standard]>=0.32` | ✓ | | | OK |
| `httpx` | service | `httpx>=0.27` | ✓ | | | OK |
| `pydantic` | service | `pydantic>=2.9` | ✓ | | | OK |
| `sqlalchemy` | service | `sqlalchemy[asyncio]>=2.0` | ✓ | | | OK |
| `alembic` | service | `alembic>=1.13` | ✓ | | | OK |
| `asyncpg` | service | `asyncpg>=0.29` | ✓ | | | OK |
| `pgvector` | service | `pgvector>=0.3` | ✓ | | | OK |
| `edge_tts` | service | `edge-tts>=6.1.0` | ✓ | | | OK |
| `pydub` | service (audio) | `pydub>=0.25.1` | ✓ | | | OK |
| `fastapi_users`, `fastapi_users_db_sqlalchemy` | service auth | `fastapi-users[sqlalchemy]>=14` | ✓ | | | OK |
| `faster_whisper` | ai-service STT | `faster-whisper>=1.0` | ✓ | | | OK |
| `huggingface_hub` | noriarm (ACT 가중치) | `huggingface_hub>=0.25` | ✓ | | | OK |
| `lerobot` | noriarm (ACT) | `lerobot>=0.1` | ✓ | | | OK |
| `scservo_sdk` | eduping (Feetech leader) | `feetech-servo-sdk>=1.0` | ✓ | | | OK |
| `PyQt5` | Admin UI | `PyQt5>=5.15` | ✓ | | | OK |
| `PyQtWebEngine` | Admin UI | `PyQtWebEngine>=5.15` | ✓ | | | OK |
| `cv_bridge`, `tf2_ros`, `tf2_geometry_msgs`, `geometry_msgs`, `sensor_msgs`, `std_msgs`, `nav2_msgs`, `nav_msgs` | ROS 노드들 전반 | (ROS apt 패키지) | — | — | ✓ `ros-jazzy-*` | OK |
| `tf_transformations` | TF 변환 헬퍼 | (apt: `ros-jazzy-tf-transformations`) | — | — | ✓ | OK |
| `xacro` | URDF macros | (apt: `ros-jazzy-xacro`) | — | — | ✓ | OK |

## 모델 가중치 (자동 다운로드 — 패키지가 아님)

| 이름 | 사용 위치 | 첫 실행 시 자동 다운로드 |
|---|---|---|
| `yolov8n.pt` (또는 YOLO-World) | perception 의 ByteTrack 추론 | `ultralytics` 가 캐시에 다운로드 (`~/.cache/ultralytics/`) |
| OSNet x0_5 ReID | perception 의 `reid_engine.py` | `torchreid` 가 `~/.cache/torch/` 에 다운로드 |
| InsightFace `buffalo_l` | perception / ai-service 얼굴 인식 | `insightface` 가 `~/.insightface/` 에 다운로드 |
| Whisper `tiny` (~75 MB) | ai-service STT | `faster-whisper` 가 `~/.cache/huggingface/hub/` 에 다운로드 |
| ACT (Action Chunking Transformer) | noriarm 블럭쌓기 | `lerobot` + `huggingface_hub` 가 첫 호출 시 다운로드 (~2 GB transitive torch 포함) |

## 누락 의존성 — 추가 권고

### 1. `torchreid` — **pyproject.toml 추가 권장**

현재 [CLAUDE.md](../CLAUDE.md) 의 `pip --break-system-packages` 명령에는 있지만 `pyproject.toml` 에 없음. perception 의 [reid_engine.py](../controller/gogoping-controller/src/gogoping/gogoping_perception/gogoping_perception/reid_engine.py) 가 사용.

추가 위치 ([pyproject.toml](../pyproject.toml) 의 `[project.dependencies]` 안, `lap` 다음 줄):

```toml
  # ReID embedding — OSNet body (perception). 첫 실행 시 가중치 자동 다운로드.
  # torch transitive 로 끌어옴 — 별도 명시 불필요.
  "torchreid",
```

### 2. `numpy` — **명시 권장 (선택)**

현재 transitive (`opencv-python-headless`, `torch` 등) 로 끌려오지만 직접 명시가 best practice. 광범위 사용.

```toml
  "numpy>=1.24",
```

### 3. `Pillow` — **명시 권장 (선택)**

`PIL` import 가 [noriarm_framework](../controller/noriarm-controller/src/noriarm_framework/) 에서. 현재 transitive 의존.

```toml
  "Pillow>=10",
```

## 이번 lost-recovery 작업 (2026-05-28) — 신규 외부 의존성

추가된 외부 의존성: **0 개**. 변경된 import 는 다음과 같으며 모두 stdlib + 워크스페이스 안:

| 새 import | 출처 | 추가 의존성 |
|---|---|---|
| `from pathlib import Path` | Python stdlib | 없음 |
| `from std_msgs.msg import Float32, String` | ROS Jazzy (apt) | 없음 (`ros-jazzy-std-msgs` 이미 있음) |
| `from gogoping_navigation.graph import Graph` | 같은 워크스페이스 (`controller/gogoping-controller/src/gogoping/gogoping_navigation`) | 없음 — `package.xml` 에 `<depend>gogoping_navigation</depend>` 추가만 |
| `from gogoping_follow.close_follow import ...` | 같은 패키지 신규 모듈 | 없음 |
| `from gogoping_follow.recovery import ...` | 같은 패키지 신규 모듈 | 없음 |

`gogoping_navigation.Graph` 자체는 `yaml` (이미 `pyyaml` 명시 ✓) 만 사용 — 추가 의존성 없음.

## 환경 셋업 명령 요약

```bash
# 1) conda env (사용자 별 명칭, 예: jazzy) 활성화
conda activate jazzy

# 2) pyproject.toml 의존성 한 번에 설치
pip install -e .

# 3) ROS 노드용 system python (sudo) — perception/camera 노드 동작에 필수
sudo apt install python3-serial ros-jazzy-cv-bridge ros-jazzy-nav2-msgs \
  ros-jazzy-tf2-ros ros-jazzy-tf2-geometry-msgs ros-jazzy-tf-transformations \
  ros-jazzy-xacro librealsense2-utils librealsense2-dev ffmpeg

sudo /usr/bin/python3 -m pip install --break-system-packages \
  "ultralytics>=8.4,<9" "lap>=0.5.12" "websockets>=13" torchreid \
  "pyrealsense2>=2.55" "aiortc>=1.9" "av>=12.0"

# 4) Intel CPU + iGPU 추가 (QSV fallback) — 선택
sudo apt install intel-media-va-driver-non-free libva-dev

# 5) NVENC 확인
ffmpeg -hide_banner -encoders 2>/dev/null | grep h264_nvenc
```

## 참고

- 패키지별 의존성 코멘트 (왜 필요한지) 는 `pyproject.toml` 에 인라인 주석으로 작성되어 있음.
- ROS 노드의 빌드 의존성은 각 패키지의 `package.xml` 에서 관리 (예: 이번 작업으로 `gogoping_follow/package.xml` 에 `<depend>gogoping_navigation</depend>` 추가).
- 새 의존성 추가 시 — pyproject.toml + 필요시 CLAUDE.md 의 system pip 리스트 + 새 ROS 패키지면 package.xml 까지 세 곳을 같이 갱신.
