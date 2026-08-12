#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv-stt/bin/python"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama was not found. Download it from: https://ollama.com/download"
  exit 1
fi

if ! curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "Starting Ollama..."
  ollama serve > /tmp/pepper-portal-ollama.log 2>&1 &
  for _ in $(seq 1 20); do
    if curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
fi

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Local speech-to-text is not set up. Run: ./setup_local_speech.sh"
  exit 1
fi

echo "Starting local MLX Whisper service. Keep this terminal open."
exec "$VENV_PYTHON" "$PROJECT_DIR/host_services/stt_server.py"
