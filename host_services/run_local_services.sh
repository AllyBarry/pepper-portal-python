#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv-stt/bin/python"

# Ollama is a Compose service now (see docker-compose.yaml); nothing to start here.
# It is reached at http://ollama:11434 from the portal container.

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Local speech-to-text is not set up. Run: ./setup_local_speech.sh"
  exit 1
fi

echo "Starting local MLX Whisper service. Keep this terminal open."
exec "$VENV_PYTHON" "$PROJECT_DIR/host_services/stt_server.py"
