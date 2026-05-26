# Path Planner / Controller 비교 실험

좁은 통로 + 동적 장애물 (유치원) 환경에서 nav2 의 planner × controller 조합을
정량 비교하는 실험 자동화. 면접용 "log 기반 incident 재현 + 정량 분석"
스킬셋 데모.

## 구조

```
scripts/path_planner_experiment/
├── README.md                    ← 본 문서
├── generate_params.py           ← 9 nav2 yaml 생성 (planner × controller)
├── run_one.py                   ← 1-run 자동화 (충전소→수면실→복귀)
├── run_all.sh                   ← 다중 run 오케스트레이션 (sc_sim 기반)
├── swap_vertex.sh               ← Dense ↔ Sparse vertex 전환
├── params/                      ← 생성된 9 nav2 yaml
│   ├── nav2_NavFn_DWB.yaml
│   ├── nav2_NavFn_MPPI.yaml
│   ├── nav2_NavFn_RPP.yaml
│   ├── nav2_Smac2D_DWB.yaml
│   ├── nav2_Smac2D_MPPI.yaml
│   ├── nav2_Smac2D_RPP.yaml
│   ├── nav2_ThetaStar_DWB.yaml
│   ├── nav2_ThetaStar_MPPI.yaml
│   └── nav2_ThetaStar_RPP.yaml
├── waypoints/                   ← Sparse vertex 설정
│   ├── sparse_waypoints.yaml    ← 7 vertex
│   └── sparse_lanes.yaml        ← 최소 lane 연결
└── analysis/
    ├── extract_metrics.py       ← 단일 bag → 메트릭 + 신뢰도 점수
    └── compare_runs.py          ← 여러 run → 매트릭스 표 / CSV / JSON
```

## 사전 환경

```bash
# 1. ROS_DOMAIN_ID + workspace + conda env 활성화
source /opt/ros/jazzy/setup.zsh
source ~/pingdergarten/install/local_setup.zsh
conda activate jazzy
export ROS_DOMAIN_ID=209  # 본인 할당 ID

# 2. apt 의존성
sudo apt install -y tmux ros-jazzy-topic-tools ros-jazzy-rosbag2-storage-mcap

# 3. Python 의존성 (워크스페이스 install 후)
pip install --break-system-packages mcap mcap-ros2-support pyyaml
```

## 실험 변수

| Axis | 후보 | 설명 |
|---|---|---|
| **Planner** | NavFn, Smac2D, ThetaStar | global planner — costmap → path |
| **Controller** | RPP, DWB, MPPI | local planner — path → cmd_vel |
| **Vertex** | Dense, Sparse | waypoints.yaml 의 vertex 밀도 |

```
총 조합 : 2 × 3 × 3 = 18 cell
반복     : 3 rep / cell
총 run  : 54
```

## 워크플로우

### Step 1 — 9 yaml 생성 (1회만)

```bash
cd scripts/path_planner_experiment
python3 generate_params.py
# → params/ 에 9 yaml 생성
```

기준 yaml 은 `controller/gogoping-controller/src/gogoping/gogoping_navigation/params/nav2_params_sim.yaml`.
이 파일을 수정하면 (예: velocity_smoother 변경) 다시 `generate_params.py` 실행으로 9 yaml 재생성.

### Step 2 — Dense vertex 실험 (현 waypoints.yaml)

```bash
bash run_all.sh --reps 3 --label dense
# → 9 cells × 3 reps = 27 runs (~2시간)
# 산출 : /tmp/runs/dense/<P>_<C>_rep<R>/
```

옵션:
```bash
# smoke test (1 rep, 30분)
bash run_all.sh --reps 1 --label smoke

# 일부 controller 만 (MPPI 제외)
bash run_all.sh --reps 1 --controllers "RPP DWB"

# 일부 planner 만
bash run_all.sh --reps 1 --planners "NavFn Smac2D"
```

### Step 3 — Sparse vertex 로 swap

`waypoints/sparse_waypoints.yaml` + `sparse_lanes.yaml` 사전 작성됨.
7 vertex (운동장 / 출입구 / 놀이방 / 놀이방5 / 수면실 / 충전소 / 충전소입구).

```bash
# Sparse 적용 (원본 자동 백업)
bash swap_vertex.sh sparse
# → /tmp/vertex_backup/ 에 원본 보관

# Sparse 실험 (sim 자동 재시작 — graph_router 새 graph 로드)
bash run_all.sh --reps 3 --label sparse

# 끝나면 Dense 복원
bash swap_vertex.sh dense

# 현재 상태 확인 언제든
bash swap_vertex.sh status
```

### Step 4 — 분석

#### 단일 run 메트릭

```bash
python3 analysis/extract_metrics.py /tmp/runs/dense/NavFn_RPP_rep1/bag/bag_0.mcap
```

출력:
```
M2 duration       : 159.6 s
M3 path length    : 21.63 m
M5 final ang jerk : 0.0379
M6 obs_min        : 0.398 m
M7 BT FAILURE     : 0
reliability       : ⚠️ 0.72 (QUESTIONABLE)
```

#### 매트릭스 비교

```bash
# 표 형식
python3 analysis/compare_runs.py /tmp/runs/dense

# CSV
python3 analysis/compare_runs.py /tmp/runs/dense --csv > dense_matrix.csv

# JSON
python3 analysis/compare_runs.py /tmp/runs/dense --json > dense_matrix.json
```

## 핵심 설계 결정

### velocity_smoother OPEN_LOOP

기준 yaml 의 `feedback: OPEN_LOOP` (default CLOSED_LOOP). 이유:
- CLOSED_LOOP 가 odom 피드백으로 ~26% 휘청 가산 (sanity 검증)
- 모든 controller 에 공통 잡음 → 공정 비교 위해 제거
- 자세한 비교: test_01 vs test_02 메트릭 참조

### cmd_vel chain 우회 (relay)

`perception.launch.py` 의 `safety_filter` 가 cmd_vel_raw → cmd_vel passthrough 담당.
sc_sim 에 perception 미포함 → `topic_tools relay` 로 우회.

→ **TODO**: perception 정상 띄우는 게 production parity. relay 는 임시.

### teleport 우회 (--skip-teleport)

`sim_teleport_node` 의 gz set_pose 가 timeout 자주 발생.
→ run_one.py 가 `--skip-teleport` 로 호출됨. 각 run 의 출발 위치는
   이전 run 의 종료 위치 (= 충전소 RETURNING 종료점).
→ 충전소 도킹 마진 ~0.30m 이내라 출발점 분산 작음.

→ **TODO**: gz set_pose timeout 근본 해결.

## 메트릭 정의

| ID | 이름 | 정의 | 단위 |
|---|---|---|---|
| M2 | duration | 시나리오 총 소요 (충전소→수면실→복귀) | s |
| M3 | path length | /odom 적분 누적 거리 | m |
| M4 | avg/max vel | /cmd_vel_nav linear.x 평균/최대 | m/s |
| M5 | jerk RMS | cmd_vel 1차 미분의 RMS (nav 출력 + final) | per sample |
| M6 | obs_min | /scan_filtered 최소 거리의 시계열 최솟값 | m |
| M7 | BT FAILURE | behavior_tree_log 의 FAILURE event 카운트 | # |

## 신뢰도 점수

각 run 의 **시뮬 부하 정상성** 을 0~1 로 정량화. 메트릭의 비교 가능성 판정.

```
reliability =
    0.35 × odom_hz_score    (target 42Hz, deadline 25Hz)
  + 0.20 × odom_stab_score  (1Hz window std → 0 이면 1.0)
  + 0.20 × cmd_vel_hz_score (target 20Hz, deadline 10Hz)
  + 0.15 × sim_clock_score  (sim_time / wall_time, target 0.95)
  + 0.10 × no_freeze_score  (odom gap > 100ms 횟수, 50 이상이면 0)
```

등급:
- `>= 0.85` ✅ RELIABLE — 분석 대상
- `>= 0.60` ⚠️ QUESTIONABLE — caveat 표기 후 포함
- `< 0.60`  ❌ UNRELIABLE — 재실행 권장

## 산출 구조

```
/tmp/runs/<label>/
├── run_all.log                          ← 실행 로그 (cell별)
├── run_summary.txt                      ← CSV (planner, controller, rep, exit, duration)
├── sc_sim_up.log                        ← device-gogoping-sim.sh up 출력
├── sc_sim_down.log
├── relay.log                            ← topic_tools relay 출력
└── <P>_<C>_rep<R>/
    ├── bag/
    │   ├── bag_0.mcap                   ← rosbag mcap
    │   └── metadata.yaml
    └── metadata.json                    ← run_id, state_history, completed
```

## 알려진 이슈

1. **gz set_pose timeout** — teleport 자주 실패. `--skip-teleport` 로 우회 중.
2. **perception safety_filter 미실행** — `topic_tools relay` 로 우회.
3. **sim_rt_factor < 0.9** — gazebo + nav2 + perception 동시 부하. CPU 50%+.
4. **MPPI timeout 가능성** — sim 부하 누적 시 240s 안에 도착 못 함. `--timeout-goto` 늘림 검토.

## 트러블슈팅

### sc_sim 이 안 떴다고 나옴

```bash
# tmux 세션 직접 확인
tmux ls
tmux attach -t gogoping-sim  # 디버그용
```

### nav2 active 도달 실패

`/tmp/runs/<label>/sc_sim_up.log` 확인. 자주:
- workspace 미빌드 → `cd ~/pingdergarten && colcon build --symlink-install`
- ROS_DOMAIN_ID 미설정
- 기존 gz sim 프로세스 남음 → `bash scripts/device-gogoping-sim.sh down`

### plugin verify 실패

새 yaml 이 적용 안 됨. install 의 symlink chain 확인:
```bash
ls -la ~/pingdergarten/controller/gogoping-controller/install/gogoping_navigation/share/gogoping_navigation/params/nav2_params_sim.yaml
# → src/.../nav2_params_sim.yaml 으로 symlink 되어야 함
```

깨졌다면 `colcon build --packages-select gogoping_navigation --symlink-install`.
