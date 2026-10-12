#!/usr/bin/env bash
# Lets phones on Pepper's Wi-Fi (`pepper-ap`) open the portal at
# http://pepper.portal instead of typing the Jetson's IP.
#
# `pepper-ap` runs in NetworkManager "shared" mode, so NetworkManager's own
# dnsmasq is the DHCP *and* DNS server for everything on that network, and it
# reads extra config from /etc/NetworkManager/dnsmasq-shared.d/. One
# `address=` line there answers pepper.portal with the Jetson's AP address.
#
# Changes nothing else: not the Jetson's hostname, /etc/hosts, the lab Wi-Fi
# or any other DNS lookup. Phones on the lab Wi-Fi ask the lab router instead,
# so the name only works on pepper-ap.
#
# Applying it re-activates pepper-ap: Pepper and any phones drop off Wi-Fi for
# a few seconds and rejoin with the same addresses.
#
# Usage:
#   sudo ./install/setup_portal_name.sh            # pepper.portal -> 192.168.50.1
#   sudo ./install/setup_portal_name.sh --remove   # undo
set -euo pipefail

NAME="${PORTAL_NAME:-pepper.portal}"
AP_ADDRESS="${PEPPER_AP_ADDRESS:-192.168.50.1}"
AP_CONNECTION="${PEPPER_AP_CONNECTION:-pepper-ap}"
CONF="/etc/NetworkManager/dnsmasq-shared.d/pepper-portal.conf"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo $0 $*" >&2
  exit 1
fi

if [ "${1:-}" = "--remove" ]; then
  rm -f "$CONF"
  echo "Removed $CONF"
else
  mkdir -p "$(dirname "$CONF")"
  cat > "$CONF" <<CONF
# Written by pepper-portal-python/install/setup_portal_name.sh
address=/$NAME/$AP_ADDRESS
CONF
  echo "Wrote $CONF: $NAME -> $AP_ADDRESS"
fi

echo "Re-activating $AP_CONNECTION (Wi-Fi drops for a few seconds)..."
nmcli connection up "$AP_CONNECTION" >/dev/null
sleep 2

if [ "${1:-}" != "--remove" ]; then
  if command -v host >/dev/null 2>&1 && host "$NAME" "$AP_ADDRESS" | grep -q "$AP_ADDRESS\$"; then
    echo "OK: $AP_ADDRESS answers $NAME. On a phone joined to $AP_CONNECTION open http://$NAME"
  else
    echo "Warning: couldn't confirm $NAME resolves via $AP_ADDRESS -- check: host $NAME $AP_ADDRESS" >&2
    exit 1
  fi
fi
