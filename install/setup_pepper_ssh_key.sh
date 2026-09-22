#!/usr/bin/env bash
# Generates (once) and installs the SSH key the portal container uses to scp
# uploaded audio onto Pepper for the Media tab's drag-and-drop upload.
# See README: "Media uploads (SSH key setup)".
#
# Safe to re-run: it reuses an existing key in the pepper-ssh-key volume
# instead of generating a new one, and ssh-copy-id is idempotent on Pepper's
# side too (it won't duplicate an already-installed key).
#
# Usage: ./install/setup_pepper_ssh_key.sh <pepper-ip> [service]
#   service defaults to pepper-portal-arm on an ARM host (Apple Silicon /
#   Raspberry Pi / Jetson), pepper-portal otherwise. Override it if you need
#   the other variant (e.g. testing the x86 image on Apple Silicon).
#
# Requires the portal image already built (docker compose build <service>) --
# this script does not trigger that build itself, since it can take a long
# time under emulation (see README's build-time warning).
set -euo pipefail

PEPPER_IP="${1:?Usage: $0 <pepper-ip> [service]}"
if [ -n "${2:-}" ]; then
  SERVICE="$2"
elif [ "$(uname -m)" = "arm64" ] || [ "$(uname -m)" = "aarch64" ]; then
  SERVICE="pepper-portal-arm"
else
  SERVICE="pepper-portal"
fi

echo "Using service: $SERVICE"
echo "Generating key in the pepper-ssh-key volume (reused if one already exists)..."
docker compose run --rm --entrypoint sh "$SERVICE" -c '
  set -e
  mkdir -p /home/user/.ssh
  chmod 700 /home/user/.ssh
  if [ -f /home/user/.ssh/id_ed25519 ]; then
    echo "Key already exists in the volume, reusing it."
  else
    ssh-keygen -t ed25519 -N "" -f /home/user/.ssh/id_ed25519 -C "pepper-portal-upload"
  fi
'

echo ""
echo "Installing the public key on Pepper (nao@${PEPPER_IP}) -- enter the nao password when prompted:"
docker compose run --rm -it --entrypoint ssh-copy-id "$SERVICE" \
  -o StrictHostKeyChecking=no -i /home/user/.ssh/id_ed25519.pub "nao@${PEPPER_IP}"

echo ""
echo "Verifying key-only login works..."
docker compose run --rm --entrypoint ssh "$SERVICE" \
  -o BatchMode=yes -o StrictHostKeyChecking=no "nao@${PEPPER_IP}" "echo SSH key auth OK"

echo ""
echo "Done. The portal container can now scp uploaded audio onto Pepper without a password."
