# -*- coding: utf-8 -*-
"""
scripter.py — simple + reliable timing (Py2.7)

Rules:
- Group by audiofile; start that audio once (if present), then schedule events
  by 'time' offset relative to that start.
- For each event: at its time, trigger ALL present fields:
  - say(text)   if 'text' exists
  - play_animation(animation) if 'animation' exists
  - (you can keep 'action' for readability, but it's optional and ignored)
- Blocking by default so an event fully completes before the next one.
"""

from __future__ import unicode_literals
import os
import io
import json
import time
import traceback
from collections import defaultdict


# ---------- logging (ASCII-safe) ----------
def _log(level, msg, verbose=True):
    if not verbose:
        return
    try:
        if isinstance(msg, unicode):  # noqa: F821 on Py3; fine on Py2
            msg = msg.encode("utf-8")
    except NameError:
        pass
    print("[SCRIPTER][%s] %s" % (level, msg))


# ---------- tiny utils ----------
def _to_float(x, default, ctx):
    try:
        return float(x)
    except Exception as e:
        _log("WARN", "Invalid number for %s -> default %s (%s: %s)" %
             (ctx, default, e.__class__.__name__, e))
        return default


def _load_json(path, verbose=True):
    if not os.path.exists(path):
        _log("ERROR", "Scene file not found: %s" % path, verbose)
        return None
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log("ERROR", "Failed to parse JSON: %s | %s" % (e.__class__.__name__, e), verbose)
        print(traceback.format_exc())
        return None


# ---------- scripter ----------
class PepperScripter(object):
    """
    Settings:
      - blocking: if True, controller calls are blocking (async_play=False)
      - verbose:  enable logs
    """

    def __init__(self, controller, blocking=True, verbose=True):
        self.controller = controller
        self.blocking = bool(blocking)
        self.verbose = bool(verbose)

    # Preferred API with `base` arg
    def run_scene(self, json_path, base=""):
        data = _load_json(json_path, self.verbose)
        if data is None:
            return False
        if not isinstance(data, dict) or "scene" not in data or not isinstance(data["scene"], list):
            _log("ERROR", "Top-level JSON must be a dict with 'scene' list", self.verbose)
            return False

        script_name = data["script_name"] if "script_name" in data else "Unnamed Script"
        _log("INFO", "Running script: %s" % script_name, self.verbose)

        base_dir = base if base else os.path.dirname(os.path.abspath(json_path))

        # Group by audiofile (events without audiofile go under None)
        groups = defaultdict(list)
        for idx, ev in enumerate(data["scene"]):
            if not isinstance(ev, dict):
                _log("WARN", "scene[%d]: not a dict; skipping" % idx, self.verbose)
                continue
            # Normalize time
            ev_time = _to_float(ev["time"], 0.0, "scene[%d].time" % idx) if "time" in ev else 0.0
            ev["_time_norm"] = ev_time  # internal
            # Bucket key
            key = ev["audiofile"] if "audiofile" in ev else None
            groups[key].append(ev)

        executed_any = False

        # Process each audio bucket independently
        for audiofile in sorted(groups, key=lambda k: "" if k is None else k):
            events = sorted(groups[audiofile], key=lambda e: e["_time_norm"])

            # Start audio if present
            start_time = time.time()
            if audiofile:
                full_audio = os.path.normpath(os.path.join(base_dir, audiofile))
                if os.path.exists(full_audio):
                    _log("INFO", "Playing audio: %s" % full_audio, self.verbose)
                    try:
                        # Start audio non-blocking so timeline can proceed
                        self.controller.play_audio(full_audio, async_play=True)
                    except Exception as e:
                        _log("ERROR", "play_audio failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                        print(traceback.format_exc())
                else:
                    _log("WARN", "Audio missing; will still run events: %s" % full_audio, self.verbose)
                start_time = time.time()  # baseline for this bucket
            else:
                _log("INFO", "No audiofile for this bucket; using now() as baseline", self.verbose)
                start_time = time.time()

            # Run each event at its offset; complete before next
            for i, ev in enumerate(events):
                # sleep until target (relative to baseline)
                target = ev["_time_norm"]
                delay = target - (time.time() - start_time)
                if delay > 0:
                    _log("INFO", "Sleeping %.3fs until event %d in this bucket" % (delay, i), self.verbose)
                    time.sleep(delay)

                # Execute ALL present fields (action is optional/hint only)
                executed_any |= self._execute_event(ev)

        if executed_any:
            _log("INFO", "Script complete: %s" % script_name, self.verbose)
        else:
            _log("WARN", "No actions executed (check fields/paths).", self.verbose)
        return executed_any

    # Back-compat alias
    def run_scene_from_file(self, json_path, base=""):
        return self.run_scene(json_path, base=base)

    # ----- per-event executor -----
    def _execute_event(self, ev):
        """
        Trigger everything present for this event.
        Event completes before the next one because calls are blocking by default.
        """
        did = False
        async_flag = (not self.blocking)

        # SAY (optional)
        if "text" in ev:
            txt = ev["text"] if ev["text"] is not None else ""
            _log("INFO", 'SAY: "%s"' % (txt,), self.verbose)
            try:
                self.controller.say(txt, async_play=async_flag)
                did = True
            except Exception as e:
                _log("ERROR", "say failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                print(traceback.format_exc())

        # ANIMATION (optional)
        if "animation" in ev:
            anim = ev["animation"]
            _log("INFO", "ANIMATION: %s" % anim, self.verbose)
            try:
                self.controller.play_animation(anim, async_play=async_flag)
                did = True
            except Exception as e:
                _log("ERROR", "play_animation failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                print(traceback.format_exc())

        # If an event also included an 'audiofile' key, it's already started at bucket start.

        return did

