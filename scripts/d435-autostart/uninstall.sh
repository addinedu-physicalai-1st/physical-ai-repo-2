#!/usr/bin/env bash
# scripts/d435-autostart/uninstall.sh — install.sh 의 reverse.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "[d435-autostart] sudo 로 실행해야 합니다 — sudo bash $0" >&2
  exit 1
fi

systemctl stop d435-streamer.service 2>/dev/null || true
systemctl disable d435-streamer.service 2>/dev/null || true
rm -f /etc/systemd/system/d435-streamer.service
rm -f /etc/udev/rules.d/99-d435-autostart.rules

systemctl daemon-reload
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=usb

echo "✓ 제거 완료."
