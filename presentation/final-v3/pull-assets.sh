#!/usr/bin/env bash
# Confluence 발표 자산 다운로드 (v2 API).
set -uo pipefail

: "${ATLASSIAN_EMAIL:?set ATLASSIAN_EMAIL}"
: "${ATLASSIAN_API_TOKEN:?set ATLASSIAN_API_TOKEN}"
command -v jq >/dev/null || { echo "jq 필요: sudo apt install jq" >&2; exit 2; }

BASE="https://woolimi.atlassian.net/wiki"
ROOT="$(cd "$(dirname "$0")" && pwd)/slides/assets/media"
AUTH=(-u "$ATLASSIAN_EMAIL:$ATLASSIAN_API_TOKEN")
OK=0; FAIL=0

mkdir -p "$ROOT/eduping" "$ROOT/noriarm" "$ROOT/gogoping" "$ROOT/doctor" "$ROOT/photos" "$ROOT/diagrams"

declare -A LIST_CACHE
list_attachments() {
  local page="$1"
  if [[ -z "${LIST_CACHE[$page]:-}" ]]; then
    LIST_CACHE[$page]=$(curl -fs "${AUTH[@]}" \
      "$BASE/api/v2/pages/$page/attachments?limit=250" \
      | jq -c '.results[] | {id: (.id | sub("^att"; "")), title}')
  fi
  printf '%s\n' "${LIST_CACHE[$page]}"
}

pull() {
  local page="$1" name="$2" dest="$3"
  if [[ -s "$dest" ]]; then
    echo "  ✓ EXIST  $(basename "$dest")"; OK=$((OK+1)); return 0
  fi
  local id
  id=$(list_attachments "$page" | jq -r --arg n "$name" 'select(.title==$n) | .id' | head -1)
  if [[ -z "$id" ]]; then
    echo "  ✗ NOFILE $name  (page=$page)"; FAIL=$((FAIL+1))
    return
  fi
  local code; code=$(curl -L -s -o "$dest.part" -w "%{http_code}" "${AUTH[@]}" \
    -H "X-Atlassian-Token: nocheck" \
    "$BASE/api/v2/attachments/$id/download")
  if [[ "$code" == "200" && -s "$dest.part" ]]; then
    mv "$dest.part" "$dest"
    echo "  ✓ $code   $(basename "$dest")  ($(du -h "$dest" | cut -f1))"; OK=$((OK+1))
  else
    rm -f "$dest.part"
    echo "  ✗ $code   $name  (id=$id)"; FAIL=$((FAIL+1))
  fi
}

echo "[EduPing — page 58622021]"
pull 58622021 "IMG_0839.MOV"                          "$ROOT/eduping/arrival.mov"
pull 58622021 "Screencast from 2026-05-27 21-36-04.mp4" "$ROOT/eduping/arrival-ui.mp4"
pull 58622021 "IMG_0840.mov"                          "$ROOT/eduping/departure.mov"
pull 58622021 "Screencast from 2026-05-27 21-37-51.mp4" "$ROOT/eduping/departure-ui.mp4"
pull 58622021 "Screencast from 2026-05-27 21-28-03.mp4" "$ROOT/eduping/dance.mp4"
pull 58622021 "Screencast from 2026-05-29 21-22-50.webm" "$ROOT/eduping/mugunghwa.webm"
pull 58622021 "IMG_0866.mov"                          "$ROOT/eduping/mugunghwa-detail.mov"
pull 58622021 "IMG_4740.mov"                          "$ROOT/eduping/safety-self.mov"
pull 58622021 "IMG_0852.mov"                          "$ROOT/eduping/safety-stop.mov"

echo; echo "[등원 하이파이브 — page 69992449]"
pull 69992449 "IMG_0868.mov"                          "$ROOT/eduping/highfive.mov"

echo; echo "[원격진찰 — page 65077274]"
pull 65077274 "IMG_0832.mov"                          "$ROOT/doctor/pointcloud.mov"
pull 65077274 "Screencast from 2026-05-26 17-08-42.webm" "$ROOT/doctor/octomap.webm"
pull 65077274 "Screencast from 2026-05-26 20-10-16.webm" "$ROOT/doctor/vision-slowdown.webm"
pull 65077274 "Screencast from 2026-05-26 16-53-35.webm" "$ROOT/doctor/impedance.webm"

echo; echo "[NoriArm — page 58359886]"
pull 58359886 "OXQuiz.webm"                           "$ROOT/noriarm/oxquiz.webm"
pull 58359886 "IMG_1307.mov"                          "$ROOT/noriarm/blocks.mov"
pull 58359886 "2026-05-29 20-06-56.mp4"               "$ROOT/noriarm/blocks-demo.mp4"
pull 58359886 "IMG_1431.MOV"                          "$ROOT/noriarm/blocks-alt.mov"

echo; echo "[Mentoring 26-05-21 — page 63471617]"
pull 63471617 "IMG_9830.jpg"                          "$ROOT/photos/hw-1.jpg"
pull 63471617 "IMG_9831.jpg"                          "$ROOT/photos/hw-2.jpg"
pull 63471617 "IMG_9832.jpg"                          "$ROOT/photos/hw-3.jpg"
pull 63471617 "IMG_9833.jpg"                          "$ROOT/photos/hw-4.jpg"
pull 63471617 "IMG_9972.jpg"                          "$ROOT/photos/team-1.jpg"
pull 63471617 "IMG_9973.jpg"                          "$ROOT/photos/team-2.jpg"

echo; echo "[diagrams — page 64454659]"
for f in mermaid_1779705947112.png mermaid_1779710163766.png mermaid_1779709789416.png \
         mermaid_1779641438852.png mermaid_1779641395899.png mermaid_1779641359294.png \
         mermaid_1779641335650.png; do
  pull 64454659 "$f"                                   "$ROOT/diagrams/$f"
done

echo
echo "================================="
echo "  OK=$OK  FAIL=$FAIL"
echo "================================="
