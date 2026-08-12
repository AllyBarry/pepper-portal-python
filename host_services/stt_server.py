#!/usr/bin/env python3
"""Loopback-only MLX Whisper service for the Pepper portal.

The Python 2 NAOqi container sends short WAV recordings to this host service.
MLX runs natively on Apple Silicon, keeping transcription on this Mac.
"""

import base64
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import mlx_whisper
except Exception as exc:  # surfaced by /status instead of crashing silently
    mlx_whisper = None
    IMPORT_ERROR = str(exc)
else:
    IMPORT_ERROR = ""


HOST = os.environ.get("PEPPER_STT_HOST", "127.0.0.1")
PORT = int(os.environ.get("PEPPER_STT_PORT", "8765"))
MODEL = os.environ.get("PEPPER_STT_MODEL", "mlx-community/whisper-tiny")
LANGUAGE = os.environ.get("PEPPER_STT_LANGUAGE", "").strip() or None
MAX_BODY_BYTES = 8 * 1024 * 1024
_transcription_lock = threading.Lock()


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "PepperLocalSTT/1.0"

    def log_message(self, message, *args):
        print("%s - %s" % (self.address_string(), message % args), flush=True)

    def respond(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/health", "/status"):
            self.respond(404, {"ok": False, "error": "Not found"})
            return
        self.respond(
            200,
            {
                "ok": True,
                "available": mlx_whisper is not None,
                "engine": "MLX Whisper",
                "model": MODEL,
                "language": LANGUAGE or "auto",
                "error": IMPORT_ERROR,
            },
        )

    def do_POST(self):
        if self.path != "/transcribe":
            self.respond(404, {"ok": False, "error": "Not found"})
            return
        if mlx_whisper is None:
            self.respond(503, {"ok": False, "error": IMPORT_ERROR or "mlx-whisper is not installed"})
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_BODY_BYTES:
                raise ValueError("Audio request must be between 1 byte and 8 MB")
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            audio = base64.b64decode(payload.get("audio_wav_base64", ""), validate=True)
            if len(audio) < 44 or not audio.startswith(b"RIFF"):
                raise ValueError("Expected a WAV audio payload")
        except Exception as exc:
            self.respond(400, {"ok": False, "error": str(exc)})
            return

        temp_path = None
        started = time.time()
        try:
            with tempfile.NamedTemporaryFile(prefix="pepper-mic-", suffix=".wav", delete=False) as temp:
                temp.write(audio)
                temp_path = temp.name

            options = {
                "path_or_hf_repo": MODEL,
                "verbose": None,
                "condition_on_previous_text": False,
            }
            if LANGUAGE:
                options["language"] = LANGUAGE

            # MLX model loading and inference share global Metal state.
            with _transcription_lock:
                result = mlx_whisper.transcribe(temp_path, **options)
            transcript = (result.get("text") or "").strip()
            self.respond(
                200,
                {
                    "ok": True,
                    "transcript": transcript,
                    "language": result.get("language") or LANGUAGE or "unknown",
                    "model": MODEL,
                    "elapsed_seconds": round(time.time() - started, 3),
                },
            )
        except Exception as exc:
            self.respond(500, {"ok": False, "error": str(exc)})
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


if __name__ == "__main__":
    print("Pepper local STT listening on http://%s:%s using %s" % (HOST, PORT, MODEL), flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
