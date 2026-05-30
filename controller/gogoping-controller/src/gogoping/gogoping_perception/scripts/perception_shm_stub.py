"""합성 shm writer — 회귀 스모크용. 실제 D435 없이 perception 노드에 프레임 공급.
usage: python3 perception_shm_stub.py [seconds]  (기본 무한, Ctrl-C 종료)
"""
import sys
import time

import numpy as np
from multiprocessing.shared_memory import SharedMemory

from gogoping_camera import shm_layout as L


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else float("inf")
    for nm in (L.SHM_COLOR_NAME, L.SHM_DEPTH_NAME, L.SHM_META_NAME):
        try:
            s = SharedMemory(name=nm); s.close(); s.unlink()
        except FileNotFoundError:
            pass
    color = SharedMemory(name=L.SHM_COLOR_NAME, create=True, size=L.COLOR_BYTES)
    depth = SharedMemory(name=L.SHM_DEPTH_NAME, create=True, size=L.DEPTH_BYTES)
    meta = SharedMemory(name=L.SHM_META_NAME, create=True, size=L.META_BYTES)
    cv, dv, mv = L.view_color(color.buf), L.view_depth(depth.buf), L.view_meta(meta.buf)
    print("shm stub up — 30fps", flush=True)
    seq, t0 = 0, time.monotonic()
    try:
        while time.monotonic() - t0 < dur:
            f = (np.random.rand(480, 640, 3) * 255).astype("uint8")
            f[150:400, 260:380] = 200
            cv[:] = f
            dv[:] = 1500
            seq += 1
            mv[0] = seq
            mv[1] = time.time_ns()
            time.sleep(1 / 30)
    except KeyboardInterrupt:
        pass
    finally:
        for s in (color, depth, meta):
            s.close()
            try:
                s.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    main()
