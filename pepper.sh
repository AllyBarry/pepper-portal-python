#!/bin/bash
#
# Single front door for day-to-day Pepper portal operation.
# One-time machine setup is install/setup_services.sh; this is what you reach
# for afterwards.
#
# Usage:
#   ./pepper.sh start      # bring the portal (+ ollama) up in the background
#   ./pepper.sh stop       # stop containers without removing them
#   ./pepper.sh restart
#   ./pepper.sh status     # docker compose ps
#   ./pepper.sh logs       # follow portal logs
#   ./pepper.sh monitor    # tmux dashboard: logs / container status / network

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

ARCH="$(uname -m)"
if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
  PORTAL_SERVICE="pepper-portal-arm"
else
  PORTAL_SERVICE="pepper-portal"
fi

SESSION="pepper"

usage() {
  echo "Usage: $0 {start|stop|restart|status|logs|monitor}" >&2
  exit 1
}

monitor() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    exec tmux attach -t "$SESSION"
  fi

  tmux new-session -d -s "$SESSION" -n portal "docker compose logs -f $PORTAL_SERVICE"
  tmux split-window -h -t "$SESSION:portal" "watch -n2 docker compose ps"

  if command -v jtop >/dev/null 2>&1; then
    tmux new-window -t "$SESSION" -n system "jtop"
  else
    tmux new-window -t "$SESSION" -n system "top"
  fi

  tmux new-window -t "$SESSION" -n network \
    "watch -n5 'echo IP address:; hostname -I; echo; ip -brief addr'"

  tmux new-window -t "$SESSION" -n shell

  tmux select-window -t "$SESSION:portal"
  exec tmux attach -t "$SESSION"
}

case "${1:-}" in
  start)   docker compose up -d "$PORTAL_SERVICE" ;;
  stop)    docker compose stop ;;
  restart) docker compose restart "$PORTAL_SERVICE" ;;
  status)  docker compose ps ;;
  logs)    docker compose logs -f "$PORTAL_SERVICE" ;;
  monitor) monitor ;;
  *)       usage ;;
esac
