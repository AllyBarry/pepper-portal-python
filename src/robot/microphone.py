# -*- coding: utf-8 -*-
import os
import threading
import time

from .base import Capability
from .errors import RobotError

SAMPLE_RATE = 16000
SILENCE_SECONDS = float(os.environ.get("PEPPER_MIC_SILENCE_SECONDS", "3"))
ENERGY_THRESHOLD = float(os.environ.get("PEPPER_MIC_ENERGY_THRESHOLD", "1200"))
ENERGY_POLL_SECONDS = 0.17
ROBOT_WAV_PATH = "/data/home/nao/pepper_portal_mic.wav"
ROBOT_WAV_KEY = "pepper_portal_mic.wav"   # the same file, as ALFileManager names it
FRONT_MIC_ONLY = [0, 0, 1, 0]             # left, right, front, rear

# One recording at a time per process; one cancel event per robot, so a new
# turn (or the Stop button) ends the previous one.
_record_lock = threading.Lock()
_cancel_lock = threading.Lock()
_cancel_events = {}


class Microphone(Capability):
    """Records one utterance with Pepper's own microphones."""

    def __init__(self, services, robot_key):
        super(Microphone, self).__init__(services)
        self._key = robot_key

    def cancel(self):
        """Stop an in-progress record_utterance(). True if one was running."""
        with _cancel_lock:
            event = _cancel_events.get(self._key)
        if event is not None:
            event.set()
        return event is not None

    def record_utterance(self, max_seconds, silence_seconds=SILENCE_SECONDS, wait_for_speech=False):
        """
        Record until `silence_seconds` of quiet after speech (or max_seconds).
        Returns (wav_bytes, pcm_byte_count, info). A cancelled recording
        returns ("", 0, info) with info["canceled"] True.

        ALAudioDevice callbacks need a robot-visible NAOqi module and don't
        work reliably through Docker NAT. So Pepper's own recorder writes the
        file on the robot, and ALFileManager returns it over the existing
        connection -- no SSH needed.
        """
        recorder = self._service("ALAudioRecorder")
        file_manager = self._service("ALFileManager")
        audio_device = self._service("ALAudioDevice")
        cancel_event = threading.Event()
        with _cancel_lock:
            previous = _cancel_events.get(self._key)
            if previous is not None:
                previous.set()
            _cancel_events[self._key] = cancel_event

        recording = False
        wav_data = None
        started_at = None
        speech_detected = False
        max_energy = 0.0
        canceled = False
        with _record_lock:
            try:
                recorder.startMicrophonesRecording(ROBOT_WAV_PATH, "wav", SAMPLE_RATE, FRONT_MIC_ONLY)
                recording = True
                audio_device.enableEnergyComputation()
                started_at = time.time()
                last_voice_at = started_at
                while True:
                    if cancel_event.is_set():
                        canceled = True
                        break
                    now = time.time()
                    energy = float(audio_device.getFrontMicEnergy())
                    max_energy = max(max_energy, energy)
                    if energy >= ENERGY_THRESHOLD:
                        speech_detected = True
                        last_voice_at = now
                    if (speech_detected or not wait_for_speech) and now - last_voice_at >= silence_seconds:
                        break
                    if now - started_at >= max_seconds:
                        break
                    time.sleep(ENERGY_POLL_SECONDS)
                recorder.stopMicrophonesRecording()
                recording = False
                wav_data = file_manager.getFileContents(ROBOT_WAV_KEY)
                if not isinstance(wav_data, bytes):
                    wav_data = bytes(wav_data)
            finally:
                if recording:
                    try:
                        recorder.stopMicrophonesRecording()
                    except Exception:
                        pass
                self._overwrite_capture(recorder)
                with _cancel_lock:
                    if _cancel_events.get(self._key) is cancel_event:
                        _cancel_events.pop(self._key, None)

        info = {
            "actual_seconds": round(time.time() - started_at, 2) if started_at else 0,
            "speech_detected": speech_detected,
            "max_energy": round(max_energy, 1),
            "energy_threshold": ENERGY_THRESHOLD,
            "silence_seconds": silence_seconds,
            "canceled": canceled,
        }
        if not wav_data or len(wav_data) <= 44 or not wav_data.startswith(b"RIFF"):
            if canceled:
                return b"", 0, info
            raise RobotError("Pepper microphone returned no WAV audio. Check ALAudioRecorder access.")
        return wav_data, max(0, len(wav_data) - 44), info

    @staticmethod
    def _overwrite_capture(recorder):
        # NAOqi 2.5's ALFileManager can read files but not delete them, so the
        # captured speech is overwritten with a near-empty recording instead.
        try:
            recorder.startMicrophonesRecording(ROBOT_WAV_PATH, "wav", SAMPLE_RATE, FRONT_MIC_ONLY)
            time.sleep(0.05)
            recorder.stopMicrophonesRecording()
        except Exception:
            try:
                recorder.stopMicrophonesRecording()
            except Exception:
                pass
