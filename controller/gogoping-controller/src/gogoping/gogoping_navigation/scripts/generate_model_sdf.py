#!/usr/bin/env python3
"""Generate models/pingdergarten/model.sdf directly from map.pgm + map.yaml.

  1) map.pgm 의 OCC 픽셀 → row-strip + vertical-merge → 직사각형 분해
  2) 짧은 변 두께로 벽 / 가구 자동 분류 후 색 분리
  3) 방별 바닥 타일 + 영어 라벨 (PIL 로 PNG 생성, PBR 텍스처로 매핑)
  4) 데코 — Vic Pinky 가 통과 못 할 좁은 통로 차단 + 야외는 벽쪽 정리
"""

from pathlib import Path
import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

# 패키지 source tree 기준 상대 경로
_PKG_ROOT = Path(__file__).resolve().parents[1]
MAP_PGM  = _PKG_ROOT / 'maps' / 'map.pgm'
MAP_YAML = _PKG_ROOT / 'maps' / 'map.yaml'
OUT_DIR  = _PKG_ROOT / 'models' / 'pingdergarten'
TEX_DIR  = OUT_DIR / 'materials' / 'textures'

FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

WALL_COLOR     = '0.96 0.93 0.85 1'
WALL_DIFFUSE   = '0.98 0.95 0.88 1'
FURN_COLOR     = '0.82 0.62 0.42 1'
FURN_DIFFUSE   = '0.92 0.72 0.50 1'

# 방 영역: (raster_x0, raster_y0, raster_x1, raster_y1, floor_rgb_0_255)
# corridor / corridor_l 은 Y 방향으로 약간 겹치게 해서 바닥 타일 끊김 방지
ROOMS_RASTER = {
    'playroom':  (1.0,   3.25, 10.64, 12.37, (255, 200, 215)),
    'sleeping':  (4.69, 12.45, 10.64, 16.93, (200, 200, 240)),
    'corridor':  (10.72, 3.25, 12.32, 12.60, (255, 245, 200)),  # north 12.37→12.60
    'corridor_l':(10.72,12.45, 12.83, 15.47, (255, 245, 200)),  # 두 타일 Y[12.45, 12.60] 겹침
    'entrance':  (10.00, 1.00, 12.32,  3.17, (255, 200, 165)),
    'outdoor':   (12.41, 1.00, 20.62,  6.99, (185, 235, 185)),
}

# 영문 라벨: 가구 없는 빈 공간에 정사각형 타일로 배치 (UV 회전 문제 회피)
# (key, text(\n 으로 줄바꿈 가능), raster_cx, raster_cy, tile_side_m, room_rgb)
LABELS = [
    ('playroom',  'PLAYROOM',           5.82, 11.50, 1.4, (255, 200, 215)),  # 책상들 북측 빈공간
    ('sleeping',  'SLEEPING\nROOM',     7.66, 13.05, 1.0, (200, 200, 240)),  # 책상 남쪽 빈공간
    ('entrance',  'ENTRANCE',          11.16,  2.10, 1.4, (255, 200, 165)),  # 입구 중앙
    ('outdoor',   'OUTDOOR\nPLAYGROUND',16.50, 4.00, 2.0, (185, 235, 185)),  # 야외 중앙 (데코 회피)
]

FLOOR_HEIGHT = 0.005
FLOOR_Z      = FLOOR_HEIGHT / 2.0
LABEL_HEIGHT = 0.004
LABEL_Z      = FLOOR_HEIGHT + LABEL_HEIGHT / 2.0
FLOOR_INSET  = 0.04

DECOS = [
    # ── 놀이방 — 책상 사이 좁은 통로 차단 ──
    ('block_pl_redbox',    3.95, 7.50, 0.20, 'box',     (0.45, 0.45, 0.40), 1.00, 0.30, 0.30),
    ('block_pl_bluebox',   3.95, 9.50, 0.20, 'box',     (0.45, 0.45, 0.40), 0.30, 0.55, 1.00),
    ('block_pl_pillar',    7.15, 7.50, 0.30, 'cylinder',(0.30, 0.60),       1.00, 0.85, 0.20),
    ('block_pl_pinkbox',  10.00, 7.50, 0.20, 'box',     (0.40, 0.40, 0.40), 1.00, 0.50, 0.70),

    # ── 수면실 — 책상 안쪽/벽쪽으로 정리, 남측 진입로 자유 ──
    # 서측 책상 옆 (서쪽 벽에서 충분히 떨어진 안쪽)
    ('ball_sl_pink',       5.40, 15.60, 0.18, 'sphere', (0.18,),            1.00, 0.65, 0.80),
    # 두 책상 사이 가장 깊은 곳 (북측 벽 근처)
    ('block_sl_purple',    7.40, 16.20, 0.20, 'box',    (0.40, 0.40, 0.40), 0.60, 0.40, 0.85),
    # 동측 책상 옆 (동쪽 벽에서 충분히 떨어진 안쪽, 도어 회피)
    ('ball_sl_yellow',     9.80, 15.60, 0.18, 'sphere', (0.18,),            1.00, 0.85, 0.30),

    # ── 입구 — 화분 두 그루 ──
    ('pot_left_stem',     10.30, 1.40, 0.15, 'cylinder',(0.13, 0.30),       0.55, 0.30, 0.20),
    ('pot_left_leaf',     10.30, 1.40, 0.42, 'sphere',  (0.18,),            0.25, 0.70, 0.30),
    ('pot_right_stem',    12.05, 1.40, 0.15, 'cylinder',(0.13, 0.30),       0.55, 0.30, 0.20),
    ('pot_right_leaf',    12.05, 1.40, 0.42, 'sphere',  (0.18,),            0.25, 0.70, 0.30),

    # ── 야외놀이터 — 모두 가장자리/벽쪽 ──
    ('slide_steps',       19.70, 5.80, 0.30, 'box',     (0.70, 0.70, 0.60), 1.00, 0.65, 0.25),
    ('slide_deck',        19.70, 4.50, 0.55, 'box',     (0.80, 1.20, 0.08), 1.00, 0.85, 0.30),
    ('slide_slope',       19.70, 3.10, 0.25, 'box',     (0.80, 1.40, 0.05), 1.00, 0.40, 0.40),
    ('seesaw_beam',       16.20, 6.50, 0.18, 'box',     (1.60, 0.20, 0.10), 0.30, 0.55, 1.00),
    ('seesaw_pivot',      16.20, 6.50, 0.08, 'cylinder',(0.10, 0.16),       0.50, 0.50, 0.50),
    ('ball_o_orange',     13.20, 5.50, 0.18, 'sphere',  (0.18,),            1.00, 0.55, 0.20),
    ('ball_o_green',      13.00, 1.50, 0.22, 'sphere',  (0.22,),            0.20, 0.85, 0.35),
    ('ball_o_purple',     20.00, 1.50, 0.20, 'sphere',  (0.20,),            0.65, 0.30, 0.85),
    ('tree_w_trunk',      13.00, 4.00, 0.45, 'cylinder',(0.10, 0.90),       0.45, 0.28, 0.18),
    ('tree_w_leaves',     13.00, 4.00, 1.10, 'sphere',  (0.45,),            0.25, 0.70, 0.30),
    ('tree_e_trunk',      17.50, 1.50, 0.45, 'cylinder',(0.10, 0.90),       0.45, 0.28, 0.18),
    ('tree_e_leaves',     17.50, 1.50, 1.10, 'sphere',  (0.45,),            0.25, 0.70, 0.30),
]

WALL_HEIGHT     = 0.72  # 벽=가구 동일 높이로 통일 (rasterization pillar 문제 회피)
WALL_Z          = WALL_HEIGHT / 2.0
FURN_HEIGHT     = 0.72  # 실제 책상 높이
FURN_Z          = FURN_HEIGHT / 2.0
WALL_FURN_SHORT_THRESHOLD = 0.15

def read_pgm(path):
    with open(path, 'rb') as f:
        assert f.readline().strip() == b'P5'
        line = f.readline()
        while line.startswith(b'#'):
            line = f.readline()
        w, h = map(int, line.split())
        int(f.readline().strip())
        data = np.frombuffer(f.read(), dtype=np.uint8).reshape(h, w)
    return data


img = read_pgm(MAP_PGM)
y = yaml.safe_load(MAP_YAML.read_text())
res = float(y['resolution'])
ox, oy, _ = y['origin']
free_thresh = float(y.get('free_thresh', 0.196))
occ_mask = img < int(free_thresh * 255)
H, W = img.shape
print(f'map.pgm: {W}x{H} px @ {res} m/px  origin=({ox},{oy})')
print(f'occupied: {int(occ_mask.sum())} ({100*occ_mask.mean():.1f}%)')


def runs_in_row(row):
    runs = []
    c = 0
    while c < len(row):
        if row[c]:
            c0 = c
            while c < len(row) and row[c]:
                c += 1
            runs.append((c0, c))
        else:
            c += 1
    return runs


rects = []
open_rect = {}
for r in range(H):
    cur = set(runs_in_row(occ_mask[r]))
    closed = [k for k in open_rect if k not in cur]
    for k in closed:
        rects.append((open_rect[k], k[0], r, k[1])); del open_rect[k]
    for run in cur:
        if run not in open_rect:
            open_rect[run] = r
for k, r0 in open_rect.items():
    rects.append((r0, k[0], H, k[1]))


def raster_to_world(xr, yr):
    return xr + ox, yr + oy


def pix_rect_to_world(r0, c0, r1, c1):
    cx_r = (c0 + c1) / 2 * res
    cy_r = (H - (r0 + r1) / 2) * res
    sx = (c1 - c0) * res
    sy = (r1 - r0) * res
    cx, cy = raster_to_world(cx_r, cy_r)
    return cx, cy, sx, sy


TEX_DIR.mkdir(parents=True, exist_ok=True)


def make_label_png(text, rgb_bg, out_path):
    """정사각 1024x1024 PNG. 다중 줄 텍스트 자동 폭 맞춤."""
    if not text:
        return False
    W = H = 1024
    img = Image.new('RGB', (W, H), rgb_bg)
    drw = ImageDraw.Draw(img)
    lines = text.split('\n')
    nlines = len(lines)
    # 폰트 사이즈 자동 (가장 긴 줄 기준 + 줄 개수 고려)
    fs = int(H * 0.45 / nlines)
    while fs > 10:
        font = ImageFont.truetype(FONT_PATH, fs)
        max_w = max(drw.textbbox((0, 0), ln, font=font)[2] for ln in lines)
        bbox_h = drw.textbbox((0, 0), 'Mg', font=font)
        line_h = bbox_h[3] - bbox_h[1] + 6
        total_h = line_h * nlines
        if max_w <= W * 0.88 and total_h <= H * 0.78:
            break
        fs -= 4
    # 그림 그리기 (그림자 + 본문)
    y0 = (H - total_h) // 2
    for i, ln in enumerate(lines):
        bb = drw.textbbox((0, 0), ln, font=font)
        tw = bb[2] - bb[0]
        x = (W - tw) // 2 - bb[0]
        yy = y0 + i * line_h - bb[1]
        drw.text((x+4, yy+4), ln, fill=(80, 80, 80), font=font)
        drw.text((x, yy), ln, fill=(15, 15, 15), font=font)
    img.save(out_path, optimize=True)
    return True


parts = [
    '<?xml version="1.0" ?>',
    '<sdf version="1.8">',
    '  <model name="pingdergarten">',
    '    <static>true</static>',
    '    <link name="link">',
    '      <pose>0 0 0 0 0 0</pose>',
]


def emit_box(name, cx, cy, cz, sx, sy, sz, ambient, diffuse,
             has_collision=True, extra_material=''):
    if has_collision:
        parts.append(f'      <collision name="{name}">')
        parts.append(f'        <pose>{cx:.4f} {cy:.4f} {cz:.4f} 0 0 0</pose>')
        parts.append(f'        <geometry><box><size>{sx:.4f} {sy:.4f} {sz:.4f}</size></box></geometry>')
        parts.append('      </collision>')
    parts.append(f'      <visual name="{name}_v">')
    parts.append(f'        <pose>{cx:.4f} {cy:.4f} {cz:.4f} 0 0 0</pose>')
    parts.append(f'        <geometry><box><size>{sx:.4f} {sy:.4f} {sz:.4f}</size></box></geometry>')
    if extra_material:
        parts.append(extra_material)
    else:
        parts.append(f'        <material><ambient>{ambient}</ambient><diffuse>{diffuse}</diffuse></material>')
    parts.append('      </visual>')


def emit_sphere(name, cx, cy, cz, r, ambient, diffuse, has_collision=True):
    if has_collision:
        parts.append(f'      <collision name="{name}">')
        parts.append(f'        <pose>{cx:.4f} {cy:.4f} {cz:.4f} 0 0 0</pose>')
        parts.append(f'        <geometry><sphere><radius>{r:.4f}</radius></sphere></geometry>')
        parts.append('      </collision>')
    parts.append(f'      <visual name="{name}_v">')
    parts.append(f'        <pose>{cx:.4f} {cy:.4f} {cz:.4f} 0 0 0</pose>')
    parts.append(f'        <geometry><sphere><radius>{r:.4f}</radius></sphere></geometry>')
    parts.append(f'        <material><ambient>{ambient}</ambient><diffuse>{diffuse}</diffuse></material>')
    parts.append('      </visual>')


def emit_cylinder(name, cx, cy, cz, r, length, ambient, diffuse, has_collision=True):
    if has_collision:
        parts.append(f'      <collision name="{name}">')
        parts.append(f'        <pose>{cx:.4f} {cy:.4f} {cz:.4f} 0 0 0</pose>')
        parts.append(f'        <geometry><cylinder><radius>{r:.4f}</radius><length>{length:.4f}</length></cylinder></geometry>')
        parts.append('      </collision>')
    parts.append(f'      <visual name="{name}_v">')
    parts.append(f'        <pose>{cx:.4f} {cy:.4f} {cz:.4f} 0 0 0</pose>')
    parts.append(f'        <geometry><cylinder><radius>{r:.4f}</radius><length>{length:.4f}</length></cylinder></geometry>')
    parts.append(f'        <material><ambient>{ambient}</ambient><diffuse>{diffuse}</diffuse></material>')
    parts.append('      </visual>')


# 1) 방 바닥 타일
floor_count = 0
for room_key, (xr0, yr0, xr1, yr1, rgb) in ROOMS_RASTER.items():
    x0 = xr0 + FLOOR_INSET; x1 = xr1 - FLOOR_INSET
    y0 = yr0 + FLOOR_INSET; y1 = yr1 - FLOOR_INSET
    sx = x1 - x0; sy = y1 - y0
    cx_r = (x0 + x1) / 2; cy_r = (y0 + y1) / 2
    cx, cy = raster_to_world(cx_r, cy_r)
    r_n, g_n, b_n = rgb[0]/255, rgb[1]/255, rgb[2]/255
    amb = f'{r_n*0.92:.3f} {g_n*0.92:.3f} {b_n*0.92:.3f} 1'
    dif = f'{r_n:.3f} {g_n:.3f} {b_n:.3f} 1'
    emit_box(f'floor_{room_key}', cx, cy, FLOOR_Z, sx, sy, FLOOR_HEIGHT, amb, dif,
             has_collision=False)
    floor_count += 1

# 1b) 영문 라벨 (정사각, 빈 공간에 위치)
label_count = 0
for room_key, label_text, rcx, rcy, side, rgb in LABELS:
    cx, cy = raster_to_world(rcx, rcy)
    png_name = f'label_{room_key}.png'
    png_path = TEX_DIR / png_name
    if make_label_png(label_text, rgb, png_path):
        mat = f"""        <material>
          <diffuse>1 1 1 1</diffuse>
          <ambient>0.9 0.9 0.9 1</ambient>
          <pbr><metal>
            <albedo_map>materials/textures/{png_name}</albedo_map>
            <metalness>0.0</metalness>
            <roughness>1.0</roughness>
          </metal></pbr>
        </material>"""
        emit_box(f'label_{room_key}', cx, cy, LABEL_Z, side, side, LABEL_HEIGHT,
                 '', '', has_collision=False, extra_material=mat)
        label_count += 1

# 2) 벽 / 가구 — 짧은 변 ≤ 0.15m → 벽(크림), 아니면 가구(우드).
#    벽 높이 == 가구 높이 (0.72m) 로 통일하여 시각적으로 pillar 현상 제거.
wall_idx = furn_idx = 0
for r0, c0, r1, c1 in rects:
    cx, cy, sx, sy = pix_rect_to_world(r0, c0, r1, c1)
    if sx < res or sy < res:
        continue
    short = min(sx, sy)
    if short <= WALL_FURN_SHORT_THRESHOLD:
        emit_box(f'wall_{wall_idx:03d}', cx, cy, WALL_Z, sx, sy, WALL_HEIGHT,
                 WALL_COLOR, WALL_DIFFUSE)
        wall_idx += 1
    else:
        emit_box(f'furn_{furn_idx:02d}', cx, cy, FURN_Z, sx, sy, FURN_HEIGHT,
                 FURN_COLOR, FURN_DIFFUSE)
        furn_idx += 1

# 3) 데코
for (name, xr, yr, cz, shape, params, R, G, B) in DECOS:
    cx, cy = raster_to_world(xr, yr)
    amb = f'{R:.2f} {G:.2f} {B:.2f} 1'
    dif = f'{min(1,R+0.1):.2f} {min(1,G+0.1):.2f} {min(1,B+0.1):.2f} 1'
    if shape == 'box':
        sx, sy, sz = params
        emit_box(name, cx, cy, cz, sx, sy, sz, amb, dif)
    elif shape == 'sphere':
        emit_sphere(name, cx, cy, cz, params[0], amb, dif)
    elif shape == 'cylinder':
        emit_cylinder(name, cx, cy, cz, params[0], params[1], amb, dif)

parts += ['    </link>', '  </model>', '</sdf>']

OUT_DIR.mkdir(parents=True, exist_ok=True)
sdf_path = OUT_DIR / 'model.sdf'
sdf_path.write_text('\n'.join(parts))
print(f'  floors: {floor_count}, labels: {label_count}')
print(f'  walls: {wall_idx}, furniture: {furn_idx}')
print(f'  decoration items: {len(DECOS)}')
print(f'Generated: {sdf_path}')

(OUT_DIR / 'model.config').write_text("""<?xml version="1.0" ?>
<model>
  <name>pingdergarten</name>
  <version>1.2</version>
  <sdf version="1.8">model.sdf</sdf>
  <author><name>Pingdergarten</name></author>
  <description>핑더가든 강의실 환경 — 색상화 + 영문 라벨 + 데코.</description>
</model>
""")
