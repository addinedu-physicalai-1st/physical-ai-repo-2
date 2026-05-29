#!/usr/bin/env bash
# scripts/d435-autostart/install.sh — D435 자동 시작 (udev + systemd) 설치.
#
# 동작:
#   - d435-streamer.service.template 의 placeholder 를 현재 sudo user / repo 로
#     치환해서 /etc/systemd/system/d435-streamer.service 로 설치
#   - /etc/udev/rules.d/99-d435-autostart.rules 설치 (USB hotplug → SYSTEMD_WANTS)
#
# 사용:
#   sudo bash scripts/d435-autostart/install.sh
#
# 자동 감지:
#   USER  = $SUDO_USER (sudo 호출자)
#   GROUP = id -gn $SUDO_USER (보통 USER 와 동일)
#   HOME  = getent passwd $SUDO_USER
#   REPO  = scripts/d435-autostart/ 의 두 단계 상위 (이 스크립트 위치 기준)
#
# ExecStart 는 ros2 launch 를 사용 — system python3 / C++ 로 실행.
# conda python(__PYTHON__)은 더 이상 ExecStart 에 불필요. ultralytics 등 게임 전용
# 패키지도 base launch 에는 불필요 (무궁화 perception 은 mugunghwa.launch.py 별도 기동).
#
# 효과:
#   - D435 (8086:0b07) 를 USB 에 꽂으면 eduping_d435_base.launch.py 자동 시작
#     (realsense2_camera + rgb/pointcloud/depth bridge + static TF)
#   - 뽑으면 자동 정지 (StopWhenUnneeded)
#   - service 가 죽으면 2초 후 재시작 (Restart=on-failure)
#
# 제거: bash scripts/d435-autostart/uninstall.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "[d435-autostart] sudo 로 실행해야 합니다 — sudo bash $0" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET_USER="${SUDO_USER:-}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  echo "[d435-autostart] SUDO_USER 가 비어 있거나 root — 일반 사용자 계정에서 sudo 로 실행해야 합니다." >&2
  exit 1
fi

TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "[d435-autostart] 감지된 설정:"
echo "  USER   = $TARGET_USER"
echo "  GROUP  = $TARGET_GROUP"
echo "  HOME   = $TARGET_HOME"
echo "  REPO   = $REPO_ROOT"
echo "  (ros2 launch 사용 — conda python 경로 불필요)"
echo

echo "[d435-autostart] systemd unit 렌더링 + 설치..."
# sed delimiter 로 '|' 사용 — 경로에 '/' 가 많아서. placeholder 가 PYTHON 경로 등에
# 포함될 가능성 없으니 안전.
sed \
  -e "s|__USER__|$TARGET_USER|g" \
  -e "s|__GROUP__|$TARGET_GROUP|g" \
  -e "s|__HOME__|$TARGET_HOME|g" \
  -e "s|__REPO_ROOT__|$REPO_ROOT|g" \
  "$SCRIPT_DIR/d435-streamer.service.template" \
  > /etc/systemd/system/d435-streamer.service
chmod 0644 /etc/systemd/system/d435-streamer.service

echo "[d435-autostart] udev rule 설치..."
install -m 0644 "$SCRIPT_DIR/99-d435-autostart.rules" /etc/udev/rules.d/99-d435-autostart.rules

echo "[d435-autostart] systemd daemon-reload..."
systemctl daemon-reload

echo "[d435-autostart] udev rule reload + trigger (이미 꽂혀 있는 D435 도 즉시 시작)..."
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=usb

echo
echo "✓ 설치 완료. 동작 확인:"
echo "  journalctl -u d435-streamer.service -f       # 로그"
echo "  systemctl status d435-streamer.service       # 상태"
echo "  curl -s http://localhost:8100/health | jq .depth   # 서버 frame 수신"
echo
echo "USB 를 뽑았다 다시 꽂아 보세요 — 자동으로 시작/정지 되는지 확인."
