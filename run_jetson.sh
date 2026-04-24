#!/bin/bash
#
# Run the Pepper portal on an NVIDIA Jetson.
# - Detached (-d) so it keeps running after you close the terminal.
# - --restart unless-stopped so it comes back after reboot / crashes.
# - -p 0.0.0.0:8080:5000 exposes the portal on port 8080 to the local network.
# - Uses the image built natively on the Jetson (arm64). If you instead need
#   to run an amd64 image under qemu, add `--platform linux/amd64` and install
#   qemu-user-static first.
#
# Usage:
#   ./run_jetson.sh            # start in background
#   docker logs -f pepper_portal   # tail logs
#   docker stop pepper_portal      # stop
#
# View from another device on the LAN:
#   http://<jetson-ip>:8080

set -e

IMAGE="${IMAGE:-pepper-portal-python:latest}"
CONTAINER="${CONTAINER:-pepper_portal}"
HOST_PORT="${HOST_PORT:-8080}"

# Print what we're about to do.
echo "Image:       $IMAGE"
echo "Container:   $CONTAINER"
echo "Host port:   $HOST_PORT (bound to 0.0.0.0 — reachable on the LAN)"
echo "Source dir:  $(pwd)/src"

# Remove any previous container so we can reuse the name.
docker rm -f "$CONTAINER" 2>/dev/null || true

docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  -v "$(pwd)/src:/home/user/src" \
  -w /home/user \
  -p 0.0.0.0:${HOST_PORT}:5000 \
  "$IMAGE"

echo
echo "Portal starting in background."
echo "LAN URL: http://$(hostname -I | awk '{print $1}'):${HOST_PORT}"
echo "Logs:    docker logs -f $CONTAINER"
echo "Stop:    docker stop $CONTAINER"
