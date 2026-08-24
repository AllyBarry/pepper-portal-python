#!/bin/bash
#
# One-time bootstrap for running the Pepper portal (+ Ollama) on this machine
# (Jetson or otherwise). Safe to re-run — every step checks state before acting.
#
# After this has run once, containers come back on every reboot on their own:
# they're started with `restart: unless-stopped` and `docker.service` is
# enabled, so Docker itself restarts them when the daemon comes up. Nothing
# needs to run at boot. Re-run this script after pulling repo changes that
# touch the Dockerfile/compose file, or to change the Ollama model.
#
# Day to day, use ./pepper.sh instead (start|stop|status|logs|monitor).
#
# Usage:
#   ./install/setup_services.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

ARCH="$(uname -m)"
if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
  PORTAL_SERVICE="pepper-portal-arm"
else
  PORTAL_SERVICE="pepper-portal"
fi
echo "Detected arch $ARCH -> using compose service '$PORTAL_SERVICE'"

# 1. Docker itself.
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found — installing via get.docker.com"
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  echo "Added $USER to the docker group — log out/in (or reboot) before continuing."
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin missing — install docker-compose-plugin for this distro and re-run." >&2
  exit 1
fi

sudo systemctl enable --now docker

# 2. QEMU binfmt handlers — only needed on ARM hosts, to run the amd64-only
#    pynaoqi SDK under emulation.
if [[ "$PORTAL_SERVICE" == "pepper-portal-arm" ]]; then
  if [ ! -e /proc/sys/fs/binfmt_misc/qemu-amd64 ]; then
    echo "Installing QEMU binfmt handlers..."
    docker compose up pepper-portal-arm-setup
  else
    echo "QEMU binfmt handlers already installed."
  fi
fi

# 3. Build + bring up the portal. `depends_on` in docker-compose.yaml pulls
#    ollama up alongside it.
echo "Building images (skips layers already built)..."
docker compose build "$PORTAL_SERVICE"

echo "Starting services..."
docker compose up -d "$PORTAL_SERVICE"

# 4. Pull the Ollama chat model once. It lives in a named volume, so this is
#    a no-op on later runs unless OLLAMA_MODEL changes.
MODEL="${OLLAMA_MODEL:-llama3.1:8b}"
if docker compose exec -T ollama ollama list 2>/dev/null | grep -q "$MODEL"; then
  echo "Ollama model $MODEL already present."
else
  echo "Pulling Ollama model $MODEL..."
  docker compose up ollama-pull
fi

echo
echo "Done. Containers restart automatically on every reboot from here on."
echo "Day to day: ./pepper.sh {start|stop|restart|status|logs|monitor}"
