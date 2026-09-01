#!/bin/bash
#
# Verify speech-to-text end to end: is the service up, and does it actually
# transcribe audio?
#
# Usage:
#   ./check_stt.sh                # synthesise or record a clip, then transcribe
#   ./check_stt.sh sample.wav     # transcribe a WAV you already have
#   ./check_stt.sh -r 5           # record 5s from the default microphone
#
# STT_URL overrides the endpoint (default http://127.0.0.1:8765). If the
# published port was remapped, use: STT_URL=http://127.0.0.1:$PEPPER_STT_HOST_PORT

set -euo pipefail

STT_URL="${STT_URL:-http://127.0.0.1:8765}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

RECORD_SECONDS=""
if [ "${1:-}" = "-r" ]; then
  RECORD_SECONDS="${2:-5}"
  shift 2 || true
fi
WAV="${1:-}"

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "python3 is required to build the request payload." >&2
  exit 1
fi

echo "==> 1/3  service reachable at $STT_URL"
if ! STATUS="$(curl -fsS --max-time 5 "$STT_URL/status")"; then
  echo "FAIL: no answer. Is it running?  docker compose ps speech-to-text" >&2
  echo "      Start it with: docker compose up -d speech-to-text" >&2
  exit 1
fi
echo "    $STATUS"
echo "$STATUS" | grep -q '"available": true' || {
  echo "FAIL: service is up but reports no usable engine (see 'error' above)." >&2
  exit 1
}

# --- obtain some audio ------------------------------------------------------
to_wav16k() {  # $1 = input, $2 = output
  ffmpeg -y -loglevel error -i "$1" -ar 16000 -ac 1 -c:a pcm_s16le "$2"
}

if [ -n "$RECORD_SECONDS" ]; then
  echo "==> 2/3  recording ${RECORD_SECONDS}s from the microphone — speak now"
  if command -v arecord >/dev/null 2>&1; then
    arecord -q -d "$RECORD_SECONDS" -f S16_LE -r 16000 -c 1 "$WORK/in.wav"
  elif command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -y -loglevel error -f avfoundation -i ":default" -t "$RECORD_SECONDS" \
      -ar 16000 -ac 1 -c:a pcm_s16le "$WORK/in.wav"
  else
    echo "No arecord or ffmpeg available to record." >&2
    exit 1
  fi
  WAV="$WORK/in.wav"
elif [ -z "$WAV" ]; then
  echo "==> 2/3  no WAV given — synthesising a known phrase"
  PHRASE="The quick brown fox jumps over the lazy dog."
  if command -v say >/dev/null 2>&1; then                      # macOS
    say -o "$WORK/in.aiff" "$PHRASE" && to_wav16k "$WORK/in.aiff" "$WORK/in.wav"
  elif command -v espeak-ng >/dev/null 2>&1; then              # Linux
    espeak-ng -w "$WORK/raw.wav" "$PHRASE" && to_wav16k "$WORK/raw.wav" "$WORK/in.wav"
  elif command -v espeak >/dev/null 2>&1; then
    espeak -w "$WORK/raw.wav" "$PHRASE" && to_wav16k "$WORK/raw.wav" "$WORK/in.wav"
  else
    echo "No speech synthesiser found (say / espeak-ng / espeak)." >&2
    echo "Record instead:  ./check_stt.sh -r 5      or pass a WAV file." >&2
    exit 1
  fi
  WAV="$WORK/in.wav"
  echo "    expected transcript: \"$PHRASE\""
else
  echo "==> 2/3  using $WAV"
fi

[ -f "$WAV" ] || { echo "No such file: $WAV" >&2; exit 1; }

# The service only accepts RIFF WAV; convert anything else if we can.
if ! head -c 4 "$WAV" | grep -q RIFF; then
  command -v ffmpeg >/dev/null 2>&1 || { echo "$WAV is not a WAV and ffmpeg is missing." >&2; exit 1; }
  to_wav16k "$WAV" "$WORK/conv.wav"
  WAV="$WORK/conv.wav"
fi

echo "==> 3/3  transcribing ($(wc -c < "$WAV" | tr -d ' ') bytes)"
"$PY" - "$WAV" "$WORK/payload.json" <<'PYEOF'
import base64, json, sys
audio = open(sys.argv[1], "rb").read()
json.dump({"audio_wav_base64": base64.b64encode(audio).decode("ascii")},
          open(sys.argv[2], "w"))
PYEOF

RESULT="$(curl -fsS --max-time 300 -X POST -H 'Content-Type: application/json' \
  --data-binary @"$WORK/payload.json" "$STT_URL/transcribe")" || {
  echo "FAIL: /transcribe rejected the request." >&2; exit 1; }

echo "$RESULT" | "$PY" -c '
import json, sys
d = json.load(sys.stdin)
if not d.get("ok"):
    print("FAIL: %s" % d.get("error")); raise SystemExit(1)
print("    transcript : %s" % d.get("transcript"))
print("    language   : %s" % d.get("language"))
print("    model      : %s" % d.get("model"))
print("    elapsed    : %ss" % d.get("elapsed_seconds"))
print("")
print("PASS" if (d.get("transcript") or "").strip() else "FAIL: empty transcript")
raise SystemExit(0 if (d.get("transcript") or "").strip() else 1)
'
