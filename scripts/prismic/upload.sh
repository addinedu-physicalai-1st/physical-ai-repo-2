#!/usr/bin/env bash
#
# Prismic Asset API 업로더
# ~/Downloads 의 이미지/동영상을 골라 Prismic CDN 에 업로드하고 URL 을 출력한다.
#
# 사용법:
#   scripts/prismic/upload.sh
#
# 준비:
#   scripts/prismic/.env.example 를 .env 로 복사하고 토큰/레포 ID 를 채운다.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOWNLOADS="${DOWNLOADS_DIR:-$HOME/Downloads}"
API_URL="https://asset-api.prismic.io/assets"

# 업로드 대상 확장자 (소문자/대문자 모두 매칭)
EXTENSIONS=(jpg jpeg png gif webp svg mp4 mov webm avi mkv)

die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
info() { printf '\033[36m%s\033[0m\n' "$*"; }

# --- 의존성 ---------------------------------------------------------------
command -v curl >/dev/null || die "curl 이 필요합니다."
command -v jq   >/dev/null || die "jq 가 필요합니다. (sudo apt install jq)"

# --- 자격증명 -------------------------------------------------------------
# 루트 .env 를 먼저 로드하고, scripts/prismic/.env 가 있으면 override.
loaded=0
for ef in "$ROOT_DIR/.env" "$SCRIPT_DIR/.env"; do
  if [[ -f "$ef" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ef"; set +a
    loaded=1
  fi
done
[[ "$loaded" -eq 1 ]] || die ".env 가 없습니다. '$ROOT_DIR/.env.example' 를 .env 로 복사해 PRISMIC_TOKEN / PRISMIC_REPOSITORY 를 채우세요."
[[ -n "${PRISMIC_TOKEN:-}" ]]      || die ".env 에 PRISMIC_TOKEN 이 비어 있습니다."
[[ -n "${PRISMIC_REPOSITORY:-}" ]] || die ".env 에 PRISMIC_REPOSITORY 가 비어 있습니다."

# --- Downloads 에서 대상 파일 수집 (최신순) -------------------------------
[[ -d "$DOWNLOADS" ]] || die "디렉토리가 없습니다: $DOWNLOADS"

# find -iname 패턴 구성 ( -iname A -o -iname B -o ... )
find_args=()
for ext in "${EXTENSIONS[@]}"; do
  [[ ${#find_args[@]} -gt 0 ]] && find_args+=(-o)
  find_args+=(-iname "*.$ext")
done

files=()
while IFS= read -r -d '' line; do
  # line: "<mtime>\t<path>" — mtime 로 정렬한 뒤 경로만 사용
  files+=("${line#*$'\t'}")
done < <(
  find "$DOWNLOADS" -maxdepth 1 -type f \( "${find_args[@]}" \) -printf '%T@\t%p\0' \
    | sort -zrn -t$'\t' -k1
)

[[ ${#files[@]} -gt 0 ]] || die "$DOWNLOADS 에 업로드할 이미지/동영상이 없습니다."

# --- 목록 출력 & 선택 -----------------------------------------------------
info "📁 $DOWNLOADS 의 업로드 가능한 파일:"
echo
for i in "${!files[@]}"; do
  f="${files[$i]}"
  size=$(du -h "$f" | cut -f1)
  printf "  \033[33m%2d\033[0m  %s  \033[90m(%s)\033[0m\n" "$((i+1))" "$(basename "$f")" "$size"
done
echo

choice=""
while true; do
  read -rp "업로드할 번호 (q 종료): " choice
  [[ "$choice" == "q" ]] && { echo "취소됨."; exit 0; }
  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#files[@]} )); then
    break
  fi
  echo "1 ~ ${#files[@]} 사이 번호를 입력하세요."
done

selected="${files[$((choice-1))]}"
info "⬆️  업로드 중: $(basename "$selected")"

# --- 업로드 ---------------------------------------------------------------
resp_file="$(mktemp)"
trap 'rm -f "$resp_file"' EXIT

http_code=$(
  curl -sS -X POST "$API_URL" \
    -H "Authorization: Bearer $PRISMIC_TOKEN" \
    -H "repository: $PRISMIC_REPOSITORY" \
    -H "Accept: application/json" \
    -F "file=@${selected}" \
    -o "$resp_file" \
    -w "%{http_code}"
)

if [[ "$http_code" != 2* ]]; then
  echo
  die "업로드 실패 (HTTP $http_code):
$(cat "$resp_file")"
fi

url=$(jq -r '.url // empty' "$resp_file")
[[ -n "$url" ]] || die "응답에 url 이 없습니다:
$(cat "$resp_file")"

echo
info "✅ 업로드 완료 — CDN URL:"
echo
printf '\033[1;32m%s\033[0m\n' "$url"
echo
