#!/bin/bash
#
# Run the Pepper portal on an NVIDIA Jetson.
# - Detached (-d) so it keeps running after you close the terminal.
# - --restart unless-stopped so it comes back after reboot / crashes.
# - -p 0.0.0.0:8080:5000 exposes the portal on port 8080 to the local network.
# - --platform linux/amd64: the NAOqi Python SDK (pynaoqi) is x86-64 only, so
#   the image must be built *and* run as amd64. On Jetson this goes through
#   qemu-user-static emulation (slow, but it works for a Flask app).
#
#   One-time setup on the Jetson:
#     sudo apt install -y qemu-user-static binfmt-support
#     docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
#
#   Build (once, or whenever the Dockerfile changes):
#     docker buildx build --platform linux/amd64 -t pepper-portal-python:latest .
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
  --platform linux/amd64 \
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
