"""뎁스카메라 뷰 자동 라이프사이클 매니저.

DepthViewer (URL /depth.html 또는 메인 UI 의 뎁스카메라 뷰 모드) 가 mount 될 때
POST /api/eduping/depth/session/start 호출. run_server.sh 가 d435 / streamer /
highfive 세 tmux window 로 같은 launch 들을 이미 띄워둔 경우엔 detect 후 attach 만
하고 종료 — 외부 (tmux) 가 lifecycle 관리. 없으면 fallback 으로 subprocess.Popen
으로 직접 spawn (예전 동작 — UI 만 띄운 dev 환경).

idempotent:
  - 외부 (tmux) launch 감지 시 attach — stop 호출에도 SIGTERM 안 보냄 (tmux 가 관리)
  - 자체 spawn 한 process 는 죽으면 자동 재기동, stop 시 SIGTERM

라이프사이클:
  1. start → 각 entry 마다 (a) 이미 alive 면 skip, (b) tmux launch 감지되면 attach,
     (c) 없으면 spawn. fire-and-forget, 즉시 반환.
  2. status → 각 entry alive/dead/pid/owner ("self" 또는 "external") 반환
  3. stop  → 자체 spawn 만 SIGTERM (3s 대기) → SIGKILL fallback. external 는 건드리지 않음.

D435 USB 점유 충돌 방지 — d435_camera 만 spawn 하면 realsense2_camera_node 하나만 USB 사용.
streamer 와 highfive_sim 은 ROS 토픽으로 데이터 받아 USB 안 건드림.

ROS 환경:
  systemd 처럼 깨끗한 env 가 필요 — control-service uvicorn 의 환경 그대로 상속 (이미
  ROS_DOMAIN_ID=203 + AMENT_PREFIX_PATH 가 set 되어 있음, run_server.sh 가 source).
  PYTHONPATH 에 service/control-service 추가 (streamer 의 control_service.streaming 의존).
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional

log = logging.getLogger(__name__)

# Repo root — control-service 가 service/control-service 아래라 ../.. 두 번.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_EDUPING_INSTALL = _REPO_ROOT / "install"
_CONTROL_SERVICE_PY = _REPO_ROOT / "service" / "control-service"
_LAUNCH_WRAPPER = _REPO_ROOT / "scripts" / "_depth_session_launch.sh"


@dataclass
class _ProcEntry:
    name: str
    cmd: list[str]
    # pgrep -f 로 외부 (tmux 등) 가 띄운 같은 launch 를 감지하는 substring.
    # 두 entry 의 패턴이 겹치지 않도록 충분히 specific.
    detect_pattern: str
    proc: Optional[subprocess.Popen] = None
    # 외부 (tmux) launch 감지 시 PID 만 저장 — 우리가 kill 하면 안 됨.
    external_pid: Optional[int] = None
    started_at: float = 0.0
    extra_env: dict[str, str] = field(default_factory=dict)
    log_path: Optional[Path] = None

    def is_alive(self) -> bool:
        if self.proc is not None:
            return self.proc.poll() is None
        if self.external_pid is not None:
            try:
                os.kill(self.external_pid, 0)
                return True
            except (ProcessLookupError, PermissionError):
                self.external_pid = None
                return False
        return False

    @property
    def owner(self) -> str:
        if self.proc is not None:
            return "self"
        if self.external_pid is not None:
            return "external"
        return "none"

    @property
    def pid(self) -> Optional[int]:
        if self.proc is not None:
            return self.proc.pid
        return self.external_pid


class DepthSession:
    """Three-launch lifecycle: d435_camera + d435_depth_streamer + highfive_sim."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._procs: dict[str, _ProcEntry] = {}
        self._define_entries()

    def _define_entries(self) -> None:
        # ROS env source — 모든 launch 가 동일하게 set.
        # control-service uvicorn 의 환경 그대로 inherit + controller install path
        # (openarm_bimanual_moveit_config, openarm_description 등) 를 ament 에 추가.
        # 이 패키지들은 controller/eduping-controller/install/ 안에 있고 project root
        # install/ 에는 없어서, 명시적으로 source.
        controller_install = _REPO_ROOT / "controller" / "eduping-controller" / "install"
        ament_extra = []
        for sub in controller_install.iterdir() if controller_install.is_dir() else []:
            if sub.is_dir() and (sub / "share").is_dir():
                ament_extra.append(str(sub))
        ament_prefix = (
            f"{os.pathsep.join(ament_extra)}{os.pathsep}{os.environ.get('AMENT_PREFIX_PATH', '')}"
            if ament_extra else os.environ.get("AMENT_PREFIX_PATH", "")
        )
        # PYTHONPATH 추가 — streamer 의 control_service.streaming + controller pkg python.
        pypath_parts = [str(_CONTROL_SERVICE_PY)]
        for sub in ament_extra:
            site = Path(sub) / "lib" / "python3.12" / "site-packages"
            if site.exists():
                pypath_parts.append(str(site))
        common_env: dict[str, str] = {
            "AMENT_PREFIX_PATH": ament_prefix,
            "PYTHONPATH": (
                f"{os.pathsep.join(pypath_parts)}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"
            ),
        }

        self._procs["d435_camera"] = _ProcEntry(
            name="d435_camera",
            cmd=[
                "ros2", "launch", "eduarm", "d435_camera.launch.py",
                "depth_width:=640", "depth_height:=480",
                "color_width:=640", "color_height:=480", "fps:=15",
            ],
            # ros2 launch parent (NOT the realsense_node child) — tmux 가 띄운 것도
            # 같은 ros2 launch 명령. realsense2_camera_node 만 살아남고 launch 만
            # 죽은 경우엔 false 가 정상 (graceful 처리 — 다시 spawn).
            detect_pattern=r"ros2 launch eduarm d435_camera\.launch\.py",
            extra_env=common_env,
            log_path=Path("/tmp/depth_session_d435.log"),
        )
        self._procs["streamer"] = _ProcEntry(
            name="streamer",
            cmd=["/usr/bin/python3", "-m", "eduarm.d435_depth_streamer",
                 "--server-host", "127.0.0.1"],
            detect_pattern=r"eduarm\.d435_depth_streamer",
            extra_env=common_env,
            log_path=Path("/tmp/depth_session_streamer.log"),
        )
        self._procs["highfive_sim"] = _ProcEntry(
            name="highfive_sim",
            cmd=["ros2", "launch", "eduarm", "highfive_sim.launch.py"],
            detect_pattern=r"ros2 launch eduarm highfive_sim\.launch\.py",
            extra_env=common_env,
            log_path=Path("/tmp/depth_session_highfive.log"),
        )

    def start(self) -> dict:
        """idempotent — 죽은 것만 다시 띄움. tmux/외부 launch 가 있으면 attach.

        Resolution order per entry:
          1. 이미 alive (자체 spawn 또는 attached external) → skip
          2. detect_pattern 으로 외부 process 발견 → attach (PID 만 기억)
          3. 둘 다 없으면 spawn (subprocess.Popen)
        """
        with self._lock:
            for entry in self._procs.values():
                if entry.is_alive():
                    log.info(f"[depth_session] {entry.name} already alive "
                             f"pid={entry.pid} owner={entry.owner}")
                    continue
                external = self._detect_existing(entry.detect_pattern)
                if external is not None:
                    entry.external_pid = external
                    entry.started_at = self._proc_start_time_s(external) or time.time()
                    log.info(f"[depth_session] {entry.name} attached to external "
                             f"pid={external} (likely tmux)")
                    continue
                self._spawn(entry)
        return self._status_locked()

    def stop(self) -> dict:
        """SIGTERM 자체 spawn 만 — external (tmux) 는 건드리지 않음."""
        with self._lock:
            for entry in self._procs.values():
                if entry.proc is None:
                    # external attach 또는 죽은 entry — kill 하지 않음.
                    continue
                if entry.proc.poll() is not None:
                    continue
                try:
                    log.info(f"[depth_session] SIGTERM {entry.name} pid={entry.proc.pid}")
                    os.killpg(os.getpgid(entry.proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except Exception as exc:
                    log.warning(f"[depth_session] {entry.name} SIGTERM 실패: {exc}")
            # Wait up to 3s for graceful exit (자체 spawn 만 대상).
            deadline = time.time() + 3.0
            for entry in self._procs.values():
                if entry.proc is None:
                    continue
                while entry.proc.poll() is None and time.time() < deadline:
                    time.sleep(0.1)
            for entry in self._procs.values():
                if entry.proc is None or entry.proc.poll() is not None:
                    continue
                try:
                    log.info(f"[depth_session] SIGKILL {entry.name}")
                    os.killpg(os.getpgid(entry.proc.pid), signal.SIGKILL)
                except (ProcessLookupError, Exception):
                    pass
        return self._status_locked()

    @staticmethod
    def _detect_existing(pattern: str) -> Optional[int]:
        """pgrep -f <pattern> → 첫 PID 반환 (없으면 None).

        본 control-service process 자신은 제외 — `pgrep -f` 가 본 모듈의 코드 (예:
        ``detect_pattern=r"ros2 launch ..."``) 를 메모리에 들고 있는 uvicorn worker
        를 match 할 수 있음. ``-x`` 는 정확 매칭이라 안 맞고, regex prefix 로 충분.
        """
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True, text=True, timeout=2,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        own_pid = os.getpid()
        for line in result.stdout.split():
            try:
                pid = int(line)
            except ValueError:
                continue
            if pid == own_pid:
                continue
            return pid
        return None

    @staticmethod
    def _proc_start_time_s(pid: int) -> Optional[float]:
        """/proc/<pid>/stat → 프로세스 시작 시각 (unix epoch seconds). 없으면 None.

        stat 의 starttime 은 jiffies (boot 이후) — `_SC_CLK_TCK` 와 /proc/stat 의
        btime 으로 unix epoch 변환.
        """
        try:
            with open(f"/proc/{pid}/stat") as f:
                fields = f.read().rsplit(")", 1)[-1].split()
            # field index 20 (after comm) → starttime in jiffies
            starttime_jiffies = int(fields[19])
            with open("/proc/stat") as f:
                btime = next(int(line.split()[1]) for line in f if line.startswith("btime"))
            hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
            return btime + starttime_jiffies / hz
        except (OSError, ValueError, StopIteration):
            return None

    def status(self) -> dict:
        with self._lock:
            return self._status_locked()

    def _status_locked(self) -> dict:
        now = time.time()
        return {
            "ok": True,
            "processes": {
                name: {
                    "alive": entry.is_alive(),
                    "pid": entry.pid,
                    "owner": entry.owner,
                    "uptime_s": (now - entry.started_at) if entry.is_alive() else None,
                    "log": (
                        str(entry.log_path)
                        if entry.log_path and entry.owner == "self"
                        else None
                    ),
                }
                for name, entry in self._procs.items()
            },
        }

    def _spawn(self, entry: _ProcEntry) -> None:
        env = os.environ.copy()
        env.update(entry.extra_env)
        log_file = entry.log_path.open("ab", buffering=0) if entry.log_path else subprocess.DEVNULL
        try:
            # setsid → 새 process group → control-service 가 죽어도 자식 살아남고,
            # 우리가 killpg 로 깔끔하게 grouptree 끝낼 수 있음.
            entry.proc = subprocess.Popen(
                entry.cmd,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            entry.started_at = time.time()
            log.info(f"[depth_session] spawned {entry.name} pid={entry.proc.pid}")
        except Exception as exc:
            log.error(f"[depth_session] {entry.name} spawn 실패: {exc}")


# Module-level singleton — 한 control-service process 안에 하나.
_session_singleton: Optional[DepthSession] = None


def get_session() -> DepthSession:
    global _session_singleton
    if _session_singleton is None:
        _session_singleton = DepthSession()
    return _session_singleton
