#!/usr/bin/env bash
# scripts/d435-autostart/install.sh — D435 자동 시작 (udev + systemd) 설치.
#
# 동작:
#   - /etc/systemd/system/d435-streamer.service  (systemd unit)
#   - /etc/udev/rules.d/99-d435-autostart.rules  (USB hotplug → SYSTEMD_WANTS)
#
# 사용:
#   sudo bash scripts/d435-autostart/install.sh
#
# 효과:
#   - D435 (8086:0b07) 를 USB 에 꽂으면 d435-streamer 자동 시작
#   - 뽑으면 자동 정지 (StopWhenUnneeded)
#   - service 가 죽으면 2초 후 재시작 (Restart=on-failure)
#
# 제거: bash scripts/d435-autostart/uninstall.sh (또는 수동 rm + udevadm reload)
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "[d435-autostart] sudo 로 실행해야 합니다 — sudo bash $0" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[d435-autostart] systemd unit 설치..."
install -m 0644 "$SCRIPT_DIR/d435-streamer.service" /etc/systemd/system/d435-streamer.service

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
