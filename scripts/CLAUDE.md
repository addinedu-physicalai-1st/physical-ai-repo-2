# scripts/

## rosbag 녹화 — `record-gogoping.sh`

GogoPing 시나리오의 토픽 트래픽을 MCAP 으로 박제. 사후 분석 / Foxglove 시각화 / planner 비교에 사용.

```bash
# 기본 (nav 표준 + 우리 debug 토픽)
scripts/record-gogoping.sh

# 라벨 붙여서 — 어떤 시나리오인지 폴더명에 박힘
scripts/record-gogoping.sh --name narrow_corridor_navfn

# 카메라 서보 명령도 같이
scripts/record-gogoping.sh --name patrol_full --with-camera

# 도움말
scripts/record-gogoping.sh --help
```

저장: `log/rosbags/<YYYY-MM-DD_HH-MM-SS>[_label]/` (gitignored). 정지는 `Ctrl+C`.

**Foxglove 로 분석**:
1. [Foxglove Studio](https://foxglove.dev/download) 설치 (무료, 모든 OS)
2. Open file → 위 폴더의 `.mcap` 선택
3. 타임라인 스크럽 + 3D LiDAR/Pose + 토픽별 차트
4. 같은 시점 NavDebugLogCard 의 `💾 Export` 와 cross-correlate

**planner 비교 워크플로우**:
```
Gazebo 시나리오 한 번 정의 (e.g., 좁은 통로 + 교실3 GOTO)
  ├─ scripts/record-gogoping.sh --name narrow_navfn       → bag 1
  ├─ (Nav2 config 의 planner 를 Smac 으로 swap)
  ├─ scripts/record-gogoping.sh --name narrow_smac        → bag 2
  └─ (또 다른 planner)
       └─ Foxglove + 메트릭 스크립트로 비교
```

**필수 의존**:
- ROS 2 jazzy + `sudo apt install ros-jazzy-rosbag2-storage-mcap`
- `ROS_DOMAIN_ID` 설정 (201~219 중 본인 할당)
- ROS sourcing (`source setup.zsh` 등)

## Confluence ↔ docs 동기화

Confluence ↔ `docs/` 동기화 도구. 진입점 두 개:

| 스크립트 | 방향 | 비고 |
|---|---|---|
| [pull_docs.sh](pull_docs.sh) | Confluence → 로컬 (pull) | 로컬 `<name>.md` 와 `<name>.assets/` 덮어씀 |
| [push_docs.sh](push_docs.sh) | 로컬 → Confluence (push) | 기본 dry-run, `--apply` 로 실제 PUT |

```bash
# Pull
scripts/pull_docs.sh              # 대화형 메뉴
scripts/pull_docs.sh 1,3,5        # 다중 선택
scripts/pull_docs.sh a            # 등록 페이지 전체
scripts/pull_docs.sh 0 <URL>      # 등록 안 된 URL 일회성

# Push (기본 dry-run)
scripts/push_docs.sh                       # 대화형 메뉴
scripts/push_docs.sh 2 --show-html         # 변환 결과 미리보기
scripts/push_docs.sh 2 --apply             # 실제 push
scripts/push_docs.sh 2 --apply --force     # 서버 버전 mismatch 무시 (위험)
scripts/push_docs.sh --file docs/x.md      # PAGES 외 임의 파일 dry-run
```

페이지 목록은 [_sync_docs/pages.sh](_sync_docs/pages.sh) — 두 스크립트가 공유. `page_id|URL+slug|출력파일명|표시라벨` 형식.

토큰은 프로젝트 루트의 [.env](../.env) 에만 두고 절대 커밋하지 않는다 (`ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`). 템플릿: [../.env.example](../.env.example).

자세한 동작: [_sync_docs/CLAUDE.md](_sync_docs/CLAUDE.md).
