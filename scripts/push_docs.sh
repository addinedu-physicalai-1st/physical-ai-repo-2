#!/usr/bin/env bash
# 대화형으로 로컬 docs/<name>.md 본문을 Confluence 페이지에 push.
#
# 메뉴:
#   1~10. 등록된 페이지 (pull_docs.sh 와 동일한 PAGES 배열 공유)
#   a.    전체
#   q.    종료
#
# 안전장치:
#   - 기본은 dry-run (변환 결과 출력만, 실제 PUT 안 함)
#   - 실제 push: --apply
#   - 서버 버전 ≠ frontmatter 버전 일 때 abort (--force 로 무시 가능)
#
# 사용법:
#   scripts/push_docs.sh                       # 메뉴 → dry-run
#   scripts/push_docs.sh 2                     # 2번 페이지 dry-run
#   scripts/push_docs.sh 2 --apply             # 2번 페이지 실제 push
#   scripts/push_docs.sh 2 --apply --force     # 버전 mismatch 무시하고 push
#   scripts/push_docs.sh 1,3,5 --apply         # 다중 push
#   scripts/push_docs.sh a --apply             # 전체 push
#   scripts/push_docs.sh --file docs/x.md      # PAGES 외 임의 파일 push (dry-run)
#   scripts/push_docs.sh --file docs/x.md --apply

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SYNC_DIR="$SCRIPT_DIR/_sync_docs"
DOCS_DIR="$ROOT_DIR/docs"

# 페이지 목록 공유
# shellcheck source=_sync_docs/pages.sh
source "$SYNC_DIR/pages.sh"

# Python: 가상환경 우선
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PY="$ROOT_DIR/.venv/bin/python"
else
  PY="python3"
fi

show_help() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; }

print_menu() {
  echo
  echo "📤 push 할 페이지를 선택하세요:"
  echo
  for i in "${!PAGES[@]}"; do
    IFS='|' read -r _ _ name label <<< "${PAGES[$i]}"
    local_md="docs/${name}.md"
    if [[ -f "$ROOT_DIR/$local_md" ]]; then
      printf "  %2d. %s  →  %s\n" $((i+1)) "$label" "$local_md"
    else
      printf "  %2d. %s  (로컬 파일 없음)\n" $((i+1)) "$label"
    fi
  done
  echo
  echo "   a. 전체 (1~${#PAGES[@]})"
  echo "   q. 종료"
  echo
}

run_push() {
  local md_path="$1"; shift
  (cd "$SYNC_DIR" && "$PY" push_page.py "$md_path" "$@")
}

# 인자 파싱
selection=""
extra_args=()
file_override=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --apply|--force|--show-html) extra_args+=("$1"); shift ;;
    --file) file_override="$2"; shift 2 ;;
    *)
      if [[ -z "$selection" ]]; then
        selection="$1"
      else
        echo "❌ 알 수 없는 인자: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

# --file 모드: 단일 파일 직접 push
if [[ -n "$file_override" ]]; then
  if [[ ! -f "$file_override" ]]; then
    echo "❌ 파일 없음: $file_override" >&2
    exit 1
  fi
  run_push "$(realpath "$file_override")" ${extra_args[@]+"${extra_args[@]}"}
  exit $?
fi

# 메뉴 입력 결정
if [[ -z "$selection" ]]; then
  print_menu
  read -rp "선택 [번호 / 1,3,5 / a / q]: " selection
fi
selection="${selection// /}"

case "$selection" in
  ""|q|Q) echo "취소됨."; exit 0 ;;
  a|A)
    indices=()
    for i in "${!PAGES[@]}"; do indices+=("$i"); done
    ;;
  *)
    indices=()
    IFS=',' read -ra parts <<< "$selection"
    for p in "${parts[@]}"; do
      if ! [[ "$p" =~ ^[0-9]+$ ]] || (( p < 1 || p > ${#PAGES[@]} )); then
        echo "❌ 잘못된 선택: '$p' (1~${#PAGES[@]}, 'a', 'q' 만 허용)" >&2
        exit 1
      fi
      indices+=("$((p-1))")
    done
    ;;
esac

# 안전장치: --apply 가 없으면 dry-run 안내
has_apply=0
for a in ${extra_args[@]+"${extra_args[@]}"}; do
  [[ "$a" == "--apply" ]] && has_apply=1
done
if (( has_apply == 0 )); then
  echo "ℹ️  dry-run 모드 (실제 push 하려면 --apply 추가)."
fi

total=${#indices[@]}
ok=0
for n in "${!indices[@]}"; do
  i=${indices[$n]}
  IFS='|' read -r pid slug name label <<< "${PAGES[$i]}"
  md_path="$DOCS_DIR/$name.md"
  echo
  echo "═══ [$((n+1))/$total] $label ═══"
  if [[ ! -f "$md_path" ]]; then
    echo "⚠ 로컬 파일 없음, 건너뜀: docs/$name.md"
    continue
  fi
  if run_push "$md_path" ${extra_args[@]+"${extra_args[@]}"}; then
    ok=$((ok+1))
  fi
done

echo
echo "결과: $ok/$total 성공"
