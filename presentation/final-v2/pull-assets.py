#!/usr/bin/env python3
"""Confluence 발표 자산 다운로드 — 브라우저 세션 쿠키 사용.

사용:
  pip install browser-cookie3 requests
  python3 pull-assets.py

브라우저 (Chrome / Chromium / Firefox) 에서 woolimi.atlassian.net 에
로그인된 상태여야 한다.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

try:
    import browser_cookie3, requests
except ImportError:
    sys.exit("pip install browser-cookie3 requests  ← 먼저 설치")

BASE = "https://woolimi.atlassian.net/wiki"
ROOT = Path(__file__).parent / "slides" / "assets" / "media"

# (pageId, filename, dest-relative-path)
JOBS = [
    # EduPing
    (58622021, "IMG_0839.MOV",                              "eduping/arrival.mov"),
    (58622021, "Screencast from 2026-05-27 21-36-04.mp4",   "eduping/arrival-ui.mp4"),
    (58622021, "IMG_0840.mov",                              "eduping/departure.mov"),
    (58622021, "Screencast from 2026-05-27 21-37-51.mp4",   "eduping/departure-ui.mp4"),
    (58622021, "Screencast from 2026-05-27 21-28-03.mp4",   "eduping/dance.mp4"),
    (58622021, "Screencast from 2026-05-29 21-22-50.webm",  "eduping/mugunghwa.webm"),
    (58622021, "IMG_0866.mov",                              "eduping/mugunghwa-detail.mov"),
    (58622021, "IMG_4740.mov",                              "eduping/safety-self.mov"),
    (58622021, "IMG_0852.mov",                              "eduping/safety-stop.mov"),
    # 등원 하이파이브
    (69992449, "IMG_0868.mov",                              "eduping/highfive.mov"),
    # 원격진찰
    (65077274, "IMG_0832.mov",                              "doctor/pointcloud.mov"),
    (65077274, "Screencast from 2026-05-26 17-08-42.webm",  "doctor/octomap.webm"),
    (65077274, "Screencast from 2026-05-26 20-10-16.webm",  "doctor/vision-slowdown.webm"),
    (65077274, "Screencast from 2026-05-26 16-53-35.webm",  "doctor/impedance.webm"),
    # NoriArm
    (58359886, "OXQuiz.webm",                               "noriarm/oxquiz.webm"),
    (58359886, "IMG_1307.mov",                              "noriarm/blocks.mov"),
    (58359886, "2026-05-29 20-06-56.mp4",                   "noriarm/blocks-demo.mp4"),
    (58359886, "IMG_1431.MOV",                              "noriarm/blocks-alt.mov"),
    # Mentoring 사진
    (63471617, "IMG_9830.jpg",                              "photos/hw-1.jpg"),
    (63471617, "IMG_9831.jpg",                              "photos/hw-2.jpg"),
    (63471617, "IMG_9832.jpg",                              "photos/hw-3.jpg"),
    (63471617, "IMG_9833.jpg",                              "photos/hw-4.jpg"),
    (63471617, "IMG_9972.jpg",                              "photos/team-1.jpg"),
    (63471617, "IMG_9973.jpg",                              "photos/team-2.jpg"),
    # GogoPing 추종 영상 (page 69402670 "추종")
    (69402670, "20260529_213106.mp4",                       "gogoping/follow.mp4"),
    # Map / Sim 사진 (page 40927273 "Map")
    (40927273, "map.png",                                   "context/map.png"),
    (40927273, "pingdergarten_gz_sim.png",                  "context/sim.png"),
    (40927273, "b55ea3bf-cf65-4e4a-b1b5-96201a883c18.png",  "context/map-alt.png"),
    (40927273, "bc3c07e5-72f4-436a-8d1a-631cc460d616.png",  "context/sim-alt.png"),
    # Architecture / Panel (page 41189416 "System Architecture")
    (41189416, "pannel-prensentation.drawio.png",           "diagrams/panel.png"),
    (41189416, "pingdergarten-diagram.drawio.png",          "diagrams/architecture.png"),
    (41189416, "Untitled Diagram-1779960469969.drawio.png", "diagrams/arch-v3.png"),
    (41189416, "Untitled Diagram-1777461129023.drawio.png", "diagrams/arch-software.png"),
    (41189416, "Untitled Diagram-1777624819005.drawio.png", "diagrams/arch-hardware.png"),
    # State machines
    (49414529, "gogoping_state_diagram.png",                "diagrams/gogoping-state.png"),
    (65306629, "pindergraten_state_diagram.drawio.png",     "diagrams/state-machine.png"),
    # Sequence (page 64880654 "Sequence_diagram")
    (64880654, "Untitled Diagram-1779793862615.drawio.png", "diagrams/seq-move.png"),
    (64880654, "Untitled Diagram-1779796043605.drawio.png", "diagrams/seq-return.png"),
    (64880654, "Untitled Diagram-1779865905242.drawio.png", "diagrams/seq-hide.png"),
    # Wake word ROC / hist (page 64454659)
    (64454659, "roc_all_variants.png",                      "diagrams/wake-roc.png"),
    (64454659, "roc_generations.png",                       "diagrams/wake-roc-gen.png"),
    (64454659, "score_hist.png",                            "diagrams/wake-hist.png"),
    # (old mermaid placeholders — leave for reference, will untouch existing)
]

def load_cookies():
    domain = "atlassian.net"
    errors = []
    for name, loader in [("chrome", browser_cookie3.chrome),
                         ("chromium", browser_cookie3.chromium),
                         ("firefox", browser_cookie3.firefox),
                         ("edge", browser_cookie3.edge),
                         ("brave", browser_cookie3.brave)]:
        try:
            jar = loader(domain_name=domain)
            n = len(list(jar))
            if n:
                print(f"[cookies] {name}: {n} 개 로드")
                return jar
        except Exception as e:
            errors.append(f"{name}: {e}")
    print("[cookies] 어느 브라우저에서도 못 가져옴:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(2)

def main():
    jar = load_cookies()
    s = requests.Session()
    s.cookies = jar
    s.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (pingdergarten-pull)"

    ROOT.mkdir(parents=True, exist_ok=True)
    for sub in {Path(d).parts[0] for _,_,d in JOBS}:
        (ROOT/sub).mkdir(exist_ok=True)

    ok = 0; fail = 0
    for page, name, rel in JOBS:
        dest = ROOT / rel
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  ✓ EXIST  {rel}")
            ok += 1
            continue
        url = f"{BASE}/download/attachments/{page}/{name}"
        try:
            r = s.get(url, allow_redirects=True, timeout=60)
            if r.status_code == 200 and len(r.content) > 0:
                dest.write_bytes(r.content)
                kb = len(r.content)//1024
                print(f"  ✓ 200   {rel}  ({kb} KB)")
                ok += 1
            else:
                print(f"  ✗ {r.status_code}   {name}")
                fail += 1
        except Exception as e:
            print(f"  ✗ ERR   {name}  ({e})")
            fail += 1

    print(f"\n=== OK={ok}  FAIL={fail}  →  {ROOT}")

if __name__ == "__main__":
    main()
