#!/usr/bin/env bash
# Installs host_services/wifi_helper.py as a systemd service on this machine
# (the Jetson), so the portal container can ask it to scan/connect the
# internal wifi NIC on Pepper's tablet "Wi-Fi Setup" screen.
#
# This deliberately runs natively, not in Docker: reconfiguring the host's
# own wifi radio needs NetworkManager's D-Bus socket and the host network
# namespace, and giving the portal container that access would also break
# its use of Compose service-name DNS (ollama, speech-to-text). See
# host_services/wifi_helper.py's module docstring for the full reasoning.
#
# Usage:
#   ./install/setup_wifi_helper.sh [interface]
#     interface defaults to wlP1p1s0 -- this project's Jetson's integrated
#     wifi NIC (see README: "Mercusys MA14H Wi-Fi Adapter Setup on Jetson"),
#     meant for the Jetson's own internet uplink. This is NOT the Mercusys
#     MA14H USB dongle (wlx088af19321e3 on that same Jetson) -- that one is
#     already dedicated as the `pepper-ap` access point Pepper itself
#     connects to, and this helper should never be pointed at it.
#     `iw dev` names interfaces per-machine, so confirm yours before running
#     this on different hardware.
#
#   Set PEPPER_WIFI_HELPER_TOKEN in the environment before running this to
#   require that token on every request (recommended if this Jetson's LAN
#   isn't fully trusted -- this endpoint can reconfigure networking). Leave
#   it unset for a quick test.
#
# Requires NetworkManager (nmcli) on this host. Jetson/JetPack images ship
# with it by default; `nmcli device status` confirms it's present and see
# what your interfaces are actually named before running this.
set -euo pipefail

IFACE="${1:-wlP1p1s0}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_PATH="/etc/systemd/system/pepper-wifi-helper.service"

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli not found. This host isn't running NetworkManager -- install it or adapt" >&2
  echo "host_services/wifi_helper.py to whatever manages wifi here (wpa_supplicant, etc)." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on this host." >&2
  exit 1
fi

echo "Interface: $IFACE"
nmcli device status | grep -q "^$IFACE " || {
  echo "Warning: '$IFACE' isn't in 'nmcli device status' output. Continuing anyway --" >&2
  echo "double check the interface name (nmcli device status) if the scan comes up empty." >&2
}

echo "Writing $UNIT_PATH ..."
sudo tee "$UNIT_PATH" >/dev/null <<EOF
[Unit]
Description=Pepper portal wifi helper (nmcli bridge for the tablet Wi-Fi Setup screen)
After=network.target NetworkManager.service

[Service]
Type=simple
ExecStart=$(command -v python3) $REPO_DIR/host_services/wifi_helper.py
Environment=PEPPER_WIFI_IFACE=$IFACE
${PEPPER_WIFI_HELPER_TOKEN:+Environment=PEPPER_WIFI_HELPER_TOKEN=$PEPPER_WIFI_HELPER_TOKEN}
Restart=on-failure
RestartSec=2
# nmcli needs to talk to NetworkManager over D-Bus as a privileged user.
User=root

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pepper-wifi-helper.service

echo ""
echo "Done. Checking it answers:"
sleep 1
curl -fsS http://127.0.0.1:8766/health && echo "" || {
  echo "Helper didn't respond -- check: sudo systemctl status pepper-wifi-helper.service" >&2
  exit 1
}
echo "sudo journalctl -u pepper-wifi-helper.service -f   # to follow logs"
