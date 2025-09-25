import os
import io
import json
import time
import traceback
from collections import defaultdict
from controller import *


# ---------- logging ----------
def _log(level, msg, verbose=True):
    if not verbose:
        return
    try:
        if isinstance(msg, unicode):  # noqa: F821 (Py3 safe)
            msg = msg.encode("utf-8")
    except NameError:
        pass
    print("[SCRIPTER][%s] %s" % (level, msg))


# ---------- utils ----------
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


# ---------- main class ----------
class PepperScripter(object):
    def __init__(self, controller, blocking=True, verbose=True):
        self.controller = controller
        self.blocking = bool(blocking)
        self.verbose = bool(verbose)

    def run_scene(self, json_path, base=""):
        data = _load_json(json_path, self.verbose)
        if data is None or not isinstance(data, dict) or "scene" not in data:
            _log("ERROR", "Invalid JSON scene structure", self.verbose)
            return False
        return self._run_data(data, base, json_path)

    def run_scene_from_file(self, json_path, base=""):
        return self.run_scene(json_path, base=base)

    # ---------- internal runner ----------
    def _run_data(self, data, base, json_path=""):
        script_name = data.get("script_name", "Unnamed Script")
        _log("INFO", "Running script: %s" % script_name, self.verbose)

        base_dir = base if base else os.path.dirname(os.path.abspath(json_path)) if json_path else os.getcwd()

        # group by audiofile
        groups = defaultdict(list)
        for idx, ev in enumerate(data["scene"]):
            if not isinstance(ev, dict):
                _log("WARN", "scene[%d] not a dict; skipping" % idx, self.verbose)
                continue
            ev_time = _to_float(ev.get("time", 0.0), 0.0, "scene[%d].time" % idx)
            ev["_time_norm"] = ev_time
            key = ev.get("audiofile")
            groups[key].append(ev)

        executed_any = False

        for audiofile, events in groups.items():
            events.sort(key=lambda e: e["_time_norm"])

            start_time = time.time()
            if audiofile:
                full_audio = os.path.normpath(os.path.join(base_dir, audiofile))
                if os.path.exists(full_audio):
                    _log("INFO", "Playing audio: %s" % full_audio, self.verbose)
                    try:
                        self.controller.play_audio(full_audio, async_play=True)
                    except Exception as e:
                        _log("ERROR", "play_audio failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                        print(traceback.format_exc())
                else:
                    _log("WARN", "Audio missing: %s" % full_audio, self.verbose)
                start_time = time.time()

            for i, ev in enumerate(events):
                target = ev["_time_norm"]
                delay = target - (time.time() - start_time)
                if delay > 0:
                    _log("INFO", "Sleeping %.2fs until event %d" % (delay, i), self.verbose)
                    time.sleep(delay)
                executed_any |= self._execute_event(ev)

        if executed_any:
            _log("INFO", "Script complete: %s" % script_name, self.verbose)
        else:
            _log("WARN", "No actions executed.", self.verbose)
        return executed_any

    def _execute_event(self, ev):
        did = False
        async_flag = (not self.blocking)

        if "text" in ev:
            txt = ev["text"] or ""
            _log("INFO", 'SAY: "%s"' % txt, self.verbose)
            try:
                
                self.controller.say(txt, async_play=async_flag)
                did = True
            except Exception as e:
                _log("ERROR", "say failed: %s | %s" % (e.__class__.__name__, e), self.verbose)

        if "animation" in ev:
            anim = ev["animation"]
            _log("INFO", "ANIMATION: %s" % anim, self.verbose)
            try:
                self.controller.play_animation(anim, async_play=async_flag)
                did = True
            except Exception as e:
                _log("ERROR", "play_animation failed: %s | %s" % (e.__class__.__name__, e), self.verbose)

        # audiofile already handled at group start
        return did




def _test():
    """Run a hardcoded test scene without any JSON file."""
    demo_scene = {
        "script_name": "DemoScript",
        "scene": [
            {
                "audiofile": "greeting.wav",
                "time": 0.0,
                "text": "what did you say to me punk",
                "animation": "animations/Stand/Gestures/Hey_1"
            },
            {
                "audiofile": "greeting.wav",
                "time": 10.0,
                "animation": "animations/Stand/Gestures/ShowSky_5"
            },
            {
                "audiofile": "greeting.wav",
                "time": 20.0,
                "text": "feeable human minds cannot comprehend such power"
            }
        ]
    }
    #ctrl = _DemoController()
    ctrl = PepperController(ip="192.168.1.8", port=9559, verbose=True)
    scripter = PepperScripter(ctrl, blocking=False, verbose=True)
    scripter._run_data(demo_scene, base=os.getcwd())


if __name__ == "__main__":
    _test()

