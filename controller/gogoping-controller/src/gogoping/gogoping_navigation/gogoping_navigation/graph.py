"""Vertex 그래프 + 다익스트라 — rclpy 무관 순수 파이썬.

waypoints.yaml 만 로드하고 lane 은 거리 < threshold 인 모든 vertex 쌍을
양방향으로 자동 연결한다. 좌표가 바뀌면 다음 인스턴스화 시 자동 반영.

사용:
    g = Graph.from_yaml(Path("config/waypoints.yaml"))
    name = g.nearest_vertex(x=2.5, y=-3.0)
    seq  = g.route("출입구1", "운동장22")   # ["출입구1", "운동장입구", "운동장41", ...]
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from math import inf, sqrt
from pathlib import Path

import yaml


DEFAULT_LANE_THRESHOLD_M = 1.71
# 같은 행/열 판정 tolerance — 두 vertex 가 같은 x 또는 y 로 정렬됐다고 볼 ∆.
AXIS_ALIGN_TOL_M = 0.10


@dataclass(frozen=True)
class Vertex:
    name: str
    x: float
    y: float
    yaw: float = 0.0
    can_rotate: bool = False


class GraphError(Exception):
    pass


def auto_edge(
    vertices: list[Vertex],
    threshold: float,
) -> list[tuple[str, str, bool]]:
    """거리 threshold 이하 모든 노드 쌍 → 양방향 lane.

    반환: ``[(from_name, to_name, bidirectional=True), ...]``. 대칭 쌍은 한 번만,
    이름 알파벳순 정렬해 결정론적 결과를 보장한다.

    Pure 함수 — Graph 인스턴스 / 파일 IO 없음. UI 의 [⚡ 자동 간선] 또는 server
    router 의 ``/waypoints/lanes/auto`` 에서 호출.
    """
    out: list[tuple[str, str, bool]] = []
    for i, a in enumerate(vertices):
        for b in vertices[i + 1:]:
            dx = a.x - b.x
            dy = a.y - b.y
            if (dx * dx + dy * dy) ** 0.5 <= threshold:
                if a.name < b.name:
                    out.append((a.name, b.name, True))
                else:
                    out.append((b.name, a.name, True))
    return out


class OccupancyCheck:
    """map.pgm + map.yaml 기반 두 점 사이 직선 점유 검사.
    Nav2 occupancy grid 와 동일 좌표계 (origin, resolution)."""

    def __init__(
        self,
        pgm_path: Path,
        origin_xy: tuple[float, float],
        resolution_m: float,
        occupied_thresh: float = 0.65,
        sample_step_m: float = 0.05,
        inflate_m: float = 0.0,
    ) -> None:
        # PGM (P5 binary 또는 P2 ASCII) 헤더 + 픽셀 로드 — Pillow 의존 회피
        with pgm_path.open("rb") as f:
            magic = f.readline().strip()
            line = f.readline()
            while line.startswith(b"#"):
                line = f.readline()
            w, h = (int(x) for x in line.split())
            maxval = int(f.readline().strip())
            if magic == b"P5":
                data = f.read(w * h)
                self._px = bytes(data)
            else:
                raise GraphError(f"unsupported pgm magic: {magic!r}")
        self._w, self._h, self._maxval = w, h, maxval
        self._origin = origin_xy
        self._res = resolution_m
        self._occupied_cutoff = (1.0 - occupied_thresh) * maxval  # ROS 관습: 어두울수록 점유
        self._step = sample_step_m
        # inflation: 샘플 점 주변 ±inflate_radius_px 정사각 영역에 점유 픽셀 있으면 점유
        self._inflate_px = max(0, int(round(inflate_m / resolution_m)))

    @classmethod
    def from_svg(
        cls,
        svg_path: Path,
        origin_xy: tuple[float, float] = (-11.0, -9.0),
        resolution_m: float = 0.025,
        size_px: tuple[int, int] = (881, 720),
        dark_cutoff: int = 80,
        sample_step_m: float = 0.05,
        inflate_m: float = 0.0,
    ) -> "OccupancyCheck":
        """admin_map.svg 의 검정 영역을 점유로 사용. PyQt 필요 (lazy import)."""
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QImage, QPainter
        from PyQt5.QtSvg import QSvgRenderer
        from PyQt5.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication([])
        w, h = size_px
        img = QImage(w, h, QImage.Format_Grayscale8)
        img.fill(255)
        qp = QPainter(img)
        qp.setRenderHint(QPainter.Antialiasing, False)
        QSvgRenderer(str(svg_path)).render(qp, QRectF(0, 0, w, h))
        qp.end()
        # raw bytes — Format_Grayscale8 은 1B/px 지만 stride 가 4 정렬일 수 있어 행별 추출
        raw = bytearray(w * h)
        for y in range(h):
            line = bytes(img.constScanLine(y).asarray(w))
            raw[y * w:(y + 1) * w] = line
        # 직접 인스턴스 만들지 말고 dummy + 필드 덮어쓰기
        inst = cls.__new__(cls)
        inst._w, inst._h, inst._maxval = w, h, 255
        inst._px = bytes(raw)
        inst._origin = origin_xy
        inst._res = resolution_m
        inst._occupied_cutoff = dark_cutoff   # 회색 < cutoff 면 점유
        inst._step = sample_step_m
        inst._inflate_px = max(0, int(round(inflate_m / resolution_m)))
        return inst

    @classmethod
    def from_map_yaml(cls, map_yaml_path: Path,
                      sample_step_m: float = 0.05,
                      inflate_m: float = 0.0) -> "OccupancyCheck":
        meta = yaml.safe_load(map_yaml_path.read_text(encoding="utf-8"))
        pgm = (map_yaml_path.parent / meta["image"]).resolve()
        ox, oy = meta["origin"][0], meta["origin"][1]
        return cls(pgm, (ox, oy), float(meta["resolution"]),
                   occupied_thresh=float(meta.get("occupied_thresh", 0.65)),
                   sample_step_m=sample_step_m,
                   inflate_m=inflate_m)

    def _world_to_px(self, x: float, y: float) -> tuple[int, int]:
        px = int(round((x - self._origin[0]) / self._res))
        py = int(round(self._h - 1 - (y - self._origin[1]) / self._res))
        return px, py

    def _occupied_at(self, px: int, py: int) -> bool:
        if not (0 <= px < self._w and 0 <= py < self._h):
            return True   # 맵 밖 = 점유로 보수
        rad = self._inflate_px
        if rad == 0:
            return self._px[py * self._w + px] < self._occupied_cutoff
        # inflation: 정사각 영역 내 점유 픽셀 있으면 점유
        for dy in range(-rad, rad + 1):
            yy = py + dy
            if not (0 <= yy < self._h):
                continue
            row = yy * self._w
            for dx in range(-rad, rad + 1):
                xx = px + dx
                if not (0 <= xx < self._w):
                    continue
                if self._px[row + xx] < self._occupied_cutoff:
                    return True
        return False

    def is_blocked(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        """두 점 사이 직선 위 sample_step 간격 샘플 중 점유 픽셀 있으면 True."""
        d = sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        n = max(2, int(d / self._step) + 1)
        for k in range(n + 1):
            t = k / n
            x = x1 + (x2 - x1) * t
            y = y1 + (y2 - y1) * t
            if self._occupied_at(*self._world_to_px(x, y)):
                return True
        return False


class Graph:
    def __init__(
        self,
        vertices: list[Vertex],
        lane_threshold_m: float = DEFAULT_LANE_THRESHOLD_M,
        axis_align_tol_m: float = AXIS_ALIGN_TOL_M,
        occupancy_check: "OccupancyCheck | None" = None,
        manual_lanes: list[tuple[str, str]] | None = None,
    ) -> None:
        """manual_lanes 가 주어지면 자동 생성 무시 — lane 은 그것만 사용 (양방향).
        manual_lanes=None 이면 거리 기반 자동 생성 (기존 동작)."""
        if not vertices:
            raise GraphError("vertices empty")
        names = [v.name for v in vertices]
        if len(names) != len(set(names)):
            dups = sorted({n for n in names if names.count(n) > 1})
            raise GraphError(f"중복 vertex name: {dups}")
        self._verts: dict[str, Vertex] = {v.name: v for v in vertices}
        self._threshold = lane_threshold_m
        self._axis_tol = axis_align_tol_m
        self._occ = occupancy_check
        if manual_lanes is not None:
            self._adj = self._build_manual_adjacency(manual_lanes)
        else:
            self._adj = self._build_adjacency()

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        lanes_path: Path | None = None,
        lane_threshold_m: float = DEFAULT_LANE_THRESHOLD_M,
        axis_align_tol_m: float = AXIS_ALIGN_TOL_M,
        occupancy_check: "OccupancyCheck | None" = None,
    ) -> "Graph":
        """waypoints.yaml 로드. lanes_path 주어지고 파일 존재하면 그 lane 만 사용,
        아니면 거리 기반 자동 생성."""
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        verts = [
            Vertex(
                name=w["name"], x=float(w["x"]), y=float(w["y"]),
                yaw=float(w.get("yaw", 0.0)),
                can_rotate=bool(w.get("can_rotate", False)),
            )
            for w in (raw.get("waypoints") or [])
        ]
        manual = None
        if lanes_path is not None and lanes_path.exists():
            lraw = yaml.safe_load(lanes_path.read_text(encoding="utf-8")) or {}
            manual = [(l["from"], l["to"]) for l in (lraw.get("lanes") or [])]
        return cls(verts, lane_threshold_m=lane_threshold_m,
                   axis_align_tol_m=axis_align_tol_m,
                   occupancy_check=occupancy_check,
                   manual_lanes=manual)

    def _build_manual_adjacency(
        self, manual_lanes: list[tuple[str, str]]
    ) -> dict[str, list[tuple[str, float]]]:
        adj: dict[str, list[tuple[str, float]]] = {n: [] for n in self._verts}
        for a, b in manual_lanes:
            if a not in self._verts or b not in self._verts:
                raise GraphError(f"lane 의 vertex 없음: {a} ↔ {b}")
            va, vb = self._verts[a], self._verts[b]
            d = sqrt((va.x - vb.x) ** 2 + (va.y - vb.y) ** 2)
            adj[a].append((b, d))
            adj[b].append((a, d))
        return adj

    def _build_adjacency(self) -> dict[str, list[tuple[str, float]]]:
        adj: dict[str, list[tuple[str, float]]] = {n: [] for n in self._verts}
        names = list(self._verts.keys())
        for i, na in enumerate(names):
            a = self._verts[na]
            for nb in names[i + 1:]:
                b = self._verts[nb]
                # 1. 같은 x 또는 같은 y 만 (대각선 제외)
                aligned = (
                    abs(a.x - b.x) < self._axis_tol
                    or abs(a.y - b.y) < self._axis_tol
                )
                if not aligned:
                    continue
                d = sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)
                # 2. 거리 임계
                if d >= self._threshold:
                    continue
                # 3. 벽/장애물 통과 검사 (occupancy_check 주어지면)
                if self._occ is not None and self._occ.is_blocked(
                    a.x, a.y, b.x, b.y
                ):
                    continue
                adj[na].append((nb, d))
                adj[nb].append((na, d))
        return adj

    @property
    def vertices(self) -> dict[str, Vertex]:
        return self._verts

    def lanes(self) -> list[tuple[str, str, float]]:
        """양방향 lane 목록 (from < to 순으로 중복 제거)."""
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str, float]] = []
        for a, neigh in self._adj.items():
            for b, d in neigh:
                key = (a, b) if a < b else (b, a)
                if key in seen:
                    continue
                seen.add(key)
                out.append((key[0], key[1], d))
        return out

    def nearest_vertex(self, x: float, y: float) -> str:
        """주어진 (x, y) 에서 가장 가까운 vertex 의 name."""
        best_name = None
        best_d = inf
        for n, v in self._verts.items():
            d = (v.x - x) ** 2 + (v.y - y) ** 2  # sqrt 생략 (단조 증가)
            if d < best_d:
                best_d = d
                best_name = n
        assert best_name is not None
        return best_name

    def route(
        self,
        src: str,
        dst: str,
        start_yaw: float | None = None,
        blocked: set[str] | None = None,
    ) -> list[str]:
        """다익스트라 — vertex name 시퀀스 (src 와 dst 포함). 경로 없으면 GraphError.

        Args:
            src: 출발 vertex name.
            dst: 목적 vertex name.
            start_yaw: 로봇 시작 heading (rad). None 이면 단순 거리 다익스트라
                (기존 호환 동작).
            blocked: 통과 금지 vertex set. dst 가 blocked 면 GraphError.

        heading-aware 모드 (start_yaw != None):
            state = (vertex_name, heading_yaw). 전이 거부 조건:
              - lane (V, W) 의 방향 angle θ_VW 와 현재 heading 의 차이 |Δ| > 135°
              - V.can_rotate=True 이면 위 조건 무시.
        """
        if src not in self._verts:
            raise GraphError(f"src '{src}' not in graph")
        if dst not in self._verts:
            raise GraphError(f"dst '{dst}' not in graph")
        blocked = blocked or set()
        if dst in blocked:
            raise GraphError(f"dst '{dst}' is blocked")
        if src == dst:
            return [src]

        if start_yaw is None:
            return self._route_simple(src, dst, blocked)
        return self._route_heading_aware(src, dst, start_yaw, blocked)

    def _route_simple(
        self, src: str, dst: str, blocked: set[str]
    ) -> list[str]:
        """기존 단순 다익스트라 — heading 무시. blocked vertex 통과 금지."""
        dist: dict[str, float] = {n: inf for n in self._verts}
        prev: dict[str, str | None] = {n: None for n in self._verts}
        dist[src] = 0.0
        pq: list[tuple[float, str]] = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            if u == dst:
                break
            for v, w in self._adj[u]:
                if v in blocked and v != dst:
                    continue
                nd = d + w
                if nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        if dist[dst] == inf:
            raise GraphError(f"no path from '{src}' to '{dst}'")
        path: list[str] = []
        cur: str | None = dst
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        return path

    def _route_heading_aware(
        self,
        src: str,
        dst: str,
        start_yaw: float,
        blocked: set[str],
    ) -> list[str]:
        """heading-aware 다익스트라 — state = (vertex, heading_yaw_bucket)."""
        from math import atan2, pi

        # heading 이산화 — 8 bucket (45° 간격)
        BUCKET_COUNT = 8
        BUCKET_RAD = 2 * pi / BUCKET_COUNT

        def bucket(yaw: float) -> int:
            normalized = (yaw + pi) % (2 * pi)  # [0, 2π)
            return int(normalized / BUCKET_RAD) % BUCKET_COUNT

        def bucket_to_yaw(b: int) -> float:
            return -pi + (b + 0.5) * BUCKET_RAD

        def angle_diff(a: float, b: float) -> float:
            d = (a - b + pi) % (2 * pi) - pi
            return abs(d)

        REVERSE_THRESHOLD = 135.0 * pi / 180.0  # 2.356 rad

        State = tuple[str, int]
        start: State = (src, bucket(start_yaw))
        dist: dict[State, float] = {start: 0.0}
        prev: dict[State, State | None] = {start: None}
        pq: list[tuple[float, State]] = [(0.0, start)]

        while pq:
            d, (u_name, u_bucket) = heapq.heappop(pq)
            if d > dist.get((u_name, u_bucket), inf):
                continue
            if u_name == dst:
                # 경로 재구성
                path: list[str] = []
                cur: State | None = (u_name, u_bucket)
                while cur is not None:
                    path.append(cur[0])
                    cur = prev[cur]
                path.reverse()
                dedup = [path[0]]
                for n in path[1:]:
                    if n != dedup[-1]:
                        dedup.append(n)
                return dedup
            u_vertex = self._verts[u_name]
            u_yaw = bucket_to_yaw(u_bucket)
            for v_name, weight in self._adj[u_name]:
                if v_name in blocked and v_name != dst:
                    continue
                v_vertex = self._verts[v_name]
                lane_yaw = atan2(
                    v_vertex.y - u_vertex.y, v_vertex.x - u_vertex.x
                )
                if not u_vertex.can_rotate:
                    if angle_diff(u_yaw, lane_yaw) > REVERSE_THRESHOLD:
                        continue
                v_state: State = (v_name, bucket(lane_yaw))
                nd = d + weight
                if nd < dist.get(v_state, inf):
                    dist[v_state] = nd
                    prev[v_state] = (u_name, u_bucket)
                    heapq.heappush(pq, (nd, v_state))

        raise GraphError(
            f"no heading-aware path from '{src}' to '{dst}' "
            f"(start_yaw={start_yaw:.2f})"
        )
