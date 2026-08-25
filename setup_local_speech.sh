#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv-stt"

# Any Apple Silicon CPython new enough for the mlx wheels will do; the pinned
# 3.13 path this script used to hardcode goes stale every Homebrew bump.
if [ -z "${PYTHON_BIN:-}" ]; then
  for candidate in /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13 \
                   /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3; do
    if [ -x "$candidate" ]; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [ -z "${PYTHON_BIN:-}" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "No suitable Python found under /opt/homebrew/bin."
  echo "Install one with: brew install python@3.13"
  echo "Or set PYTHON_BIN to a Python 3.9+ Apple Silicon installation and retry."
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg is required. Install it with: brew install ffmpeg"
  exit 1
fi

echo "Using $PYTHON_BIN ($("$PYTHON_BIN" -c 'import platform; print(platform.python_version(), platform.machine())'))"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/host_services/requirements.txt"

echo "Local speech setup complete. Start it with: ./run_local_services.sh"
