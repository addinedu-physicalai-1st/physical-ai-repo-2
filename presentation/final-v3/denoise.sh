#!/usr/bin/env bash
# 영상 배경소음 감쇠 — ffmpeg afftdn 필터.
# 원본 보존, *.dn.{ext} 로 저장.
#
# 사용:
#   bash denoise.sh                              # 전체 일괄
#   bash denoise.sh slides/assets/media/...mov   # 한 파일만 (튜닝용)
#   NR=25 NF=-25 bash denoise.sh                 # 더 세게
#
# 튜닝 가이드:
#   NR (감쇠 강도 dB)   기본 20.  10=약함, 30=강함(쇠소리 가능)
#   NF (노이즈 floor)   기본 -30. -25=소음만 더 잘라냄, -35=더 보존
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)/slides/assets/media"
NR="${NR:-20}"
NF="${NF:-30}"
FILTER="afftdn=nr=${NR}:nf=-${NF}"

process() {
  local in="$1"
  [[ ! -f "$in" ]] && { echo "  ! 없음: $in"; return; }
  local ext="${in##*.}"
  local base="${in%.*}"
  local out="${base}.dn.${ext}"
  [[ -f "$out" && "$out" -nt "$in" ]] && { echo "  · skip  $(basename "$out")"; return; }
  echo "  ⏳ $(basename "$in")  → ${FILTER}"
  ffmpeg -y -i "$in" -af "$FILTER" -c:v copy -c:a aac -b:a 128k "$out" \
    -loglevel error 2>&1
  if [[ -s "$out" ]]; then
    echo "  ✓ $(basename "$out")  ($(du -h "$out" | cut -f1))"
  else
    echo "  ✗ 실패: $in"
    rm -f "$out"
  fi
}

if [[ "${1:-}" ]]; then
  process "$1"
else
  shopt -s nullglob
  for f in "$ROOT"/{eduping,gogoping,doctor,noriarm}/*.{mov,mp4,webm,MOV}; do
    [[ "$f" == *.dn.* ]] && continue
    process "$f"
  done
  echo
  echo "끝. *.dn.{mov,mp4,webm} 파일을 들어보고 OK 면:"
  echo "  ls slides/assets/media/*/*.dn.* | while read f; do mv -v \"\$f\" \"\${f%.dn.*}.\${f##*.}\"; done"
fi
