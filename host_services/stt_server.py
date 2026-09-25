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
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# arecord is optional: the STT server still handles pre-recorded WAVs even when
# /dev/snd isn't mapped (dev machines without a mic).
ARECORD_PATH = shutil.which("arecord")
CAPTURE_MAX_SECONDS = 60
CAPTURE_SAMPLE_RATE = 16000  # what whisper expects

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
        if self.path == "/devices":
            self.respond(200, {
                "ok": True,
                "arecord_available": bool(ARECORD_PATH),
                "devices": list_capture_devices(),
            })
            return
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
                "arecord_available": bool(ARECORD_PATH),
                "error": IMPORT_ERROR,
            },
        )

    def do_POST(self):
        if self.path == "/capture":
            self._handle_capture()
            return
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

    def _handle_capture(self):
        if ENGINE is None:
            self.respond(503, {"ok": False, "error": IMPORT_ERROR or "no speech engine installed"})
            return
        if not ARECORD_PATH:
            self.respond(503, {
                "ok": False,
                "error": "arecord not installed. Rebuild speech-to-text: docker compose build speech-to-text",
            })
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size).decode("utf-8")) if size else {}
            device = (payload.get("device") or "default").strip() or "default"
            duration = float(payload.get("duration_seconds") or 5)
            if duration <= 0 or duration > CAPTURE_MAX_SECONDS:
                raise ValueError(
                    "duration_seconds must be between 0 and %d" % CAPTURE_MAX_SECONDS
                )
        except Exception as exc:
            self.respond(400, {"ok": False, "error": str(exc)})
            return

        temp_path = None
        started = time.time()
        try:
            with tempfile.NamedTemporaryFile(prefix="jetson-mic-", suffix=".wav", delete=False) as temp:
                temp_path = temp.name
            _run_arecord(device, duration, temp_path)
            capture_finished = time.time()
            with _transcription_lock:
                transcript, detected = ENGINE.transcribe(temp_path)
            wav_bytes = b""
            try:
                with open(temp_path, "rb") as fh:
                    wav_bytes = fh.read()
            except Exception:
                pass
            self.respond(
                200,
                {
                    "ok": True,
                    "transcript": transcript,
                    "language": detected or LANGUAGE or "unknown",
                    "model": ENGINE.model,
                    "device": device,
                    "capture_seconds": round(capture_finished - started, 3),
                    "transcription_seconds": round(time.time() - capture_finished, 3),
                    "audio_wav_base64": base64.b64encode(wav_bytes).decode("ascii") if wav_bytes else "",
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


_ARECORD_LINE_RE = re.compile(
    r"^card (?P<card>\d+): (?P<card_id>\S+) \[(?P<card_name>[^\]]+)\],"
    r" device (?P<device>\d+): (?P<device_id>.+?) \[(?P<device_name>[^\]]*)\]"
)


def list_capture_devices():
    """Return `arecord -l` parsed into a list the UI can render.

    Empty list is meaningful: the container can't see any mic (no /dev/snd
    mapping, no USB mic plugged in, or arecord missing). The status endpoint
    already reports arecord_available so the UI can nudge the operator.
    """
    if not ARECORD_PATH:
        return []
    try:
        proc = subprocess.run(
            [ARECORD_PATH, "-l"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except Exception:
        return []
    devices = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        match = _ARECORD_LINE_RE.match(line)
        if not match:
            continue
        card = int(match.group("card"))
        device = int(match.group("device"))
        devices.append({
            "hw": "plughw:%d,%d" % (card, device),
            "card": card,
            "device": device,
            "card_id": match.group("card_id"),
            "card_name": match.group("card_name"),
            "device_name": match.group("device_name") or match.group("device_id"),
            "label": "%s - %s (hw %d,%d)" % (
                match.group("card_name"),
                match.group("device_name") or match.group("device_id"),
                card,
                device,
            ),
        })
    return devices


def _run_arecord(device, duration_seconds, out_path):
    """Blocking capture into `out_path`. Raises RuntimeError on failure."""
    if not ARECORD_PATH:
        raise RuntimeError("arecord is not installed in this container")
    cmd = [
        ARECORD_PATH,
        "-D", device,
        "-f", "S16_LE",
        "-c", "1",
        "-r", str(CAPTURE_SAMPLE_RATE),
        "-t", "wav",
        "-d", str(int(round(duration_seconds))),
        "-q",
        out_path,
    ]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=duration_seconds + 15,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(
            "arecord failed (%d) on %s: %s" % (proc.returncode, device, err or "no stderr")
        )


if __name__ == "__main__":
    print(
        "Pepper STT listening on http://%s:%s using %s (%s)"
        % (HOST, PORT, ENGINE.model if ENGINE else "no engine", ENGINE.name if ENGINE else IMPORT_ERROR),
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
