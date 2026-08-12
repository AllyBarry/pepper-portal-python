#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.13}"
VENV_DIR="$PROJECT_DIR/.venv-stt"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python 3.13 was not found at $PYTHON_BIN"
  echo "Set PYTHON_BIN to a Python 3.8+ Apple Silicon installation and retry."
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg is required. Install it with: brew install ffmpeg"
  exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/host_services/requirements.txt"

echo "Local speech setup complete. Start it with: ./run_local_services.sh"
