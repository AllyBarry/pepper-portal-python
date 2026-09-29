#!/usr/bin/env bash
# Lets containers (the portal) reach Pepper on the `pepper-ap` access point.
#
# `pepper-ap` uses NetworkManager's `ipv4.method shared` (README: "Create the
# Pepper Access Point"), which installs FORWARD rules that only accept *new*
# connections into the AP interface from the AP subnet itself, and REJECT
# everything else. The host can ping Pepper (not forwarded), but Docker bridge
# traffic (172.16.0.0/12) is forwarded and gets rejected -- inside the
# container that shows up as `ping: Destination Port Unreachable`.
#
# This installs a NetworkManager dispatcher script that puts an ACCEPT rule for
# Docker-bridge -> AP traffic at the top of FORWARD every time the AP comes up
# (NetworkManager rebuilds its rules on each up, so a one-off iptables command
# doesn't survive a reboot), and applies it once now. Replies are already
# allowed by NetworkManager's ESTABLISHED,RELATED rule, and Docker's MASQUERADE
# makes Pepper see the traffic as coming from 192.168.50.1.
#
# Usage:
#   sudo ./install/setup_ap_docker_forward.sh [interface]
#     interface defaults to wlx088af19321e3, the Mercusys MA14H dongle that
#     serves `pepper-ap` on this project's Jetson. Check `nmcli device status`
#     for the name on other hardware.
set -euo pipefail

IFACE="${1:-wlx088af19321e3}"
DOCKER_NETS="172.16.0.0/12"
HOOK_PATH="/etc/NetworkManager/dispatcher.d/90-pepper-ap-docker-forward"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: this writes to /etc/NetworkManager and changes iptables." >&2
  exit 1
fi

IPTABLES="$(command -v iptables)" || {
  echo "iptables not found." >&2
  exit 1
}

cat > "$HOOK_PATH" <<EOF
#!/bin/sh
# Installed by pepper-portal-python/install/setup_ap_docker_forward.sh.
# Lets Docker containers reach devices on the $IFACE access point.
[ "\$1" = "$IFACE" ] && [ "\$2" = "up" ] || exit 0
# Delete-then-insert keeps exactly one copy, always ahead of NetworkManager's REJECT.
while $IPTABLES -D FORWARD -s $DOCKER_NETS -o $IFACE -j ACCEPT 2>/dev/null; do :; done
$IPTABLES -I FORWARD 1 -s $DOCKER_NETS -o $IFACE -j ACCEPT
EOF
chmod 755 "$HOOK_PATH"
echo "Installed $HOOK_PATH"

# Apply now instead of waiting for the next AP restart.
"$HOOK_PATH" "$IFACE" up
echo "FORWARD rule active:"
"$IPTABLES" -S FORWARD | grep -- "-o $IFACE" || true
