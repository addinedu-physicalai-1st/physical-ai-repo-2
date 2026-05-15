# gogoping-controller

GogoPing 로봇 ROS2 워크스페이스. 라즈베리파이 + 노트북 분할 빌드 (`scripts/device-gogoping-pi.sh` / `scripts/device-gogoping-laptop.sh`).

## 설계 문서 (FSM / BT)

FSM 및 Behavior Tree 관련 모든 설계는 [docs/](docs/) 디렉토리에 있다.

| 문서 | 내용 |
|---|---|
| [docs/gogoping-file-structure.md](docs/gogoping-file-structure.md) | `src/gogoping/` 패키지별 폴더 구조 + behavior 별 책임 + "Used in:" 역참조 |
| [docs/state-bt.md](docs/state-bt.md) | FSM 6 states (CHARGING / IDLE / ASSIST / PLAY / RETURNING / ERROR) × MainTree 구조 + 트리 컨벤션 |
| [docs/subtree-flow.md](docs/subtree-flow.md) | SubTree 5종 (Carry / Follow / Lullaby / HideAndSeek / Return) 의 자세한 노드 흐름 |
| [docs/blackboard-schema.md](docs/blackboard-schema.md) | Blackboard 키 목록 + R/W 매트릭스 + 초기값 |
| [docs/fsm-triggers.md](docs/fsm-triggers.md) | FSM trigger 이름 / kwargs / 전이 다이어그램 |
| [docs/conventions.md](docs/conventions.md) | `context.py` / behavior DI / `main.py` BT swap 패턴 + 코딩 체크리스트 |
| [docs/py-trees-spike.md](docs/py-trees-spike.md) | py_trees Parallel + Monitor RUNNING 동작 검증 (30분 spike, 본격 코딩 전 1회) |
| [docs/graph-routing.md](docs/graph-routing.md) | vertex/lane 그래프 + 다익스트라 — 어디서 어떻게 호출하나 (BT / ROS / REST / Admin UI) |
| [docs/bt/](docs/bt/) | BT 트리/behavior 별 상세 — `bt/behaviors/<category>.md` (입출력 blackboard·액션) + `bt/trees/<tree>.md` (root composite·trigger 매트릭스). 새 behavior/트리 추가 시 갱신 컨벤션은 [docs/bt/README.md](docs/bt/README.md) 참조 |

ROS 서비스 / 메시지 계약은 `src/gogoping/gogoping_msgs/{srv,msg,action}/` 의 `.srv` / `.msg` 파일이 **곧 spec** — 외부 (UI / Control Server) 와의 인터페이스 변경 시 여기부터.

## ⚠️ 변경 시 사용자 확인 필요

다음 항목 중 하나라도 **다르게 정의하려고 하면 반드시 사용자에게 먼저 확인**한다. 무단 변경 금지:

- **폴더 구조** — `src/gogoping/` 하위 패키지 추가/삭제/이름변경, `gogoping_modes/gogoping_modes/{fsm,bt,interfaces,utils}` 의 하위 구조 변경
- **FSM state** — 6 states (CHARGING / IDLE / ASSIST / PLAY / RETURNING / ERROR) 추가/삭제/이름변경, transition 규칙 변경
- **BT 구조** — MainTree 6개 / SubTree 5개 의 구성 변경, behavior 카테고리 (common / navigation / perception / follow / manual / recovery) 추가/삭제

위 세 가지는 6명 코드베이스의 뼈대다. 한 명이 조용히 바꾸면 다른 사람 코드가 다 깨진다. 작은 추가 (behavior 한 개 추가, blackboard 키 한 개 추가 등) 는 사용자 확인 없이 진행해도 OK 지만 문서 (docs/blackboard-schema.md 등) 는 같이 갱신할 것.

## 최상위 [/docs/](../../docs/) 와의 관계

최상위 `/docs/` 의 [folder-structure.md](../../docs/folder-structure.md) / [system-architecture.md](../../docs/system-architecture.md) / [implementation-plan.md](../../docs/implementation-plan.md) 에 FSM·BT 관련 내용이 일부 요약되어 있으나, **본 디렉토리 (`controller/gogoping-controller/docs/`) 가 source of truth** 다.

- 최상위 `/docs/` 는 Confluence 양방향 동기화 대상 — 전체 시스템 관점의 요약.
- `controller/gogoping-controller/docs/` 는 구현에 직접 쓰이는 상세 명세.
- 두 곳의 내용이 충돌하거나 다를 경우 **`controller/gogoping-controller/docs/` 를 따른다**. 최상위 문서의 차이는 발견 시 후속 동기화에서 수정.

## 패키지별 상세

추가 CLAUDE.md 가 있는 패키지:

- [src/gogoping/gogoping_camera/CLAUDE.md](src/gogoping/gogoping_camera/CLAUDE.md) — USB 카메라 → UDP MJPEG 송출 (SR-CAM-001)
