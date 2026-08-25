#!/usr/bin/env python3
"""Speech-to-text service for the Pepper portal.

The Python 2 NAOqi container sends short WAV recordings here over HTTP.

Two interchangeable backends sit behind one wire format:

  mlx    - MLX Whisper on Apple Silicon. Uses the Mac GPU via Metal, so it only
           works when run directly on the host (./run_local_services.sh).
  faster - faster-whisper (CTranslate2) on CPU. Portable, so this is what the
           `speech-to-text` Compose service runs. Docker Desktop cannot pass
           Metal through to a container, which is why MLX is not an option there.

PEPPER_STT_ENGINE picks one; the default probes for MLX and falls back.
"""

import base64
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("PEPPER_STT_HOST", "127.0.0.1")
PORT = int(os.environ.get("PEPPER_STT_PORT", "8765"))
LANGUAGE = os.environ.get("PEPPER_STT_LANGUAGE", "").strip() or None
ENGINE_CHOICE = os.environ.get("PEPPER_STT_ENGINE", "auto").strip().lower()
MAX_BODY_BYTES = 8 * 1024 * 1024

# Model naming differs per backend: MLX loads an HF repo, faster-whisper takes a
# bare size name. Only fall back to a per-engine default when nothing is set.
MODEL_OVERRIDE = os.environ.get("PEPPER_STT_MODEL", "").strip() or None
MLX_DEFAULT_MODEL = "mlx-community/whisper-tiny"
FASTER_DEFAULT_MODEL = "tiny"

# Both backends keep global state during load and inference, so requests are
# serialised. ThreadingHTTPServer still lets /health answer while one is running.
_transcription_lock = threading.Lock()


class MlxEngine(object):
    name = "MLX Whisper"

    def __init__(self):
        import mlx_whisper

        self._mlx_whisper = mlx_whisper
        self.model = MODEL_OVERRIDE or MLX_DEFAULT_MODEL

    def transcribe(self, path):
        options = {
            "path_or_hf_repo": self.model,
            "verbose": None,
            "condition_on_previous_text": False,
        }
        if LANGUAGE:
            options["language"] = LANGUAGE
        result = self._mlx_whisper.transcribe(path, **options)
        return (result.get("text") or "").strip(), result.get("language")


class FasterWhisperEngine(object):
    name = "faster-whisper (CPU)"

    def __init__(self):
        from faster_whisper import WhisperModel

        self.model = MODEL_OVERRIDE or FASTER_DEFAULT_MODEL
        # int8 roughly halves latency versus float32 on CPU; the accuracy cost is
        # negligible for the short, close-mic clips Pepper sends.
        self._model = WhisperModel(
            self.model,
            device=os.environ.get("PEPPER_STT_DEVICE", "cpu"),
            compute_type=os.environ.get("PEPPER_STT_COMPUTE_TYPE", "int8"),
            download_root=os.environ.get("PEPPER_STT_CACHE_DIR") or None,
        )

    def transcribe(self, path):
        segments, info = self._model.transcribe(
            path,
            language=LANGUAGE,
            condition_on_previous_text=False,
        )
        # segments is a generator; consuming it is what actually runs inference.
        text = "".join(segment.text for segment in segments).strip()
        return text, getattr(info, "language", None)


def load_engine(choice):
    attempts = {"mlx": [MlxEngine], "faster": [FasterWhisperEngine]}.get(
        choice, [MlxEngine, FasterWhisperEngine]
    )
    errors = []
    for factory in attempts:
        try:
            return factory(), ""
        except Exception as exc:  # surfaced by /status instead of crashing silently
            errors.append("%s: %s" % (factory.name, exc))
    return None, "; ".join(errors)


ENGINE, IMPORT_ERROR = load_engine(ENGINE_CHOICE)


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
                "available": ENGINE is not None,
                "engine": ENGINE.name if ENGINE else "none",
                "model": ENGINE.model if ENGINE else "",
                "language": LANGUAGE or "auto",
                "error": IMPORT_ERROR,
            },
        )

    def do_POST(self):
        if self.path != "/transcribe":
            self.respond(404, {"ok": False, "error": "Not found"})
            return
        if ENGINE is None:
            self.respond(503, {"ok": False, "error": IMPORT_ERROR or "no speech engine installed"})
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

            with _transcription_lock:
                transcript, detected = ENGINE.transcribe(temp_path)
            self.respond(
                200,
                {
                    "ok": True,
                    "transcript": transcript,
                    "language": detected or LANGUAGE or "unknown",
                    "model": ENGINE.model,
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
    print(
        "Pepper STT listening on http://%s:%s using %s (%s)"
        % (HOST, PORT, ENGINE.model if ENGINE else "no engine", ENGINE.name if ENGINE else IMPORT_ERROR),
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
