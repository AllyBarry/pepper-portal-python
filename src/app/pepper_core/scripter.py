import os
import io
import json
import time
import traceback

# ---------------- logging ----------------
def _log(level, msg, verbose=True):
    if not verbose:
        return
    try:
        if isinstance(msg, unicode):  # noqa: F821 (Py3 safe)
            msg = msg.encode("utf-8")
    except NameError:
        pass
    print("[SCRIPTER][%s] %s" % (level, msg))


# ---------------- utils ----------------
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

def _is_str(x):
    try:
        basestring  # noqa
        return isinstance(x, basestring)
    except NameError:
        return isinstance(x, str)

def _as_list(val):
    if val is None:
        return []
    if _is_str(val):
        return [val]
    return list(val) if isinstance(val, list) else [val]

def _resolve_audio_path(audiofile, audio_source, base_dir):
    rel = (audiofile or "").replace("\\", "/")
    if not rel:
        return None
    if rel.startswith("/"):
        return os.path.normpath(rel)
    if audio_source:
        return os.path.normpath(os.path.join(audio_source, rel))
    return os.path.normpath(os.path.join(base_dir, rel))

def _parse_await_policy(row):
    """
    Returns dict flags for groups: {'audio': bool|None, 'tts': bool|None, 'anim': bool|None}
    Precedence:
      1) await_audio / await_tts / await_anim booleans on the row
      2) 'await' string or list on the row
      3) None -> use default rule (arrays wait, scalars don't)
    """
    flags = {}
    # explicit per-group booleans
    for k, g in (("await_audio", "audio"), ("await_tts", "tts"), ("await_anim", "anim")):
        if k in row:
            try:
                flags[g] = bool(row[k])
            except Exception:
                pass

    if "await" in row:
        a = row.get("await")
        if _is_str(a):
            a = [a]
        if isinstance(a, list):
            aset = set([str(x).lower() for x in a])
            if "all" in aset:
                flags.setdefault("audio", True)
                flags.setdefault("tts", True)
                flags.setdefault("anim", True)
            elif "none" in aset:
                flags.setdefault("audio", False)
                flags.setdefault("tts", False)
                flags.setdefault("anim", False)
            else:
                if "audio" in aset:
                    flags.setdefault("audio", True)
                if "tts" in aset or "say" in aset or "text" in aset or "texts" in aset:
                    flags.setdefault("tts", True)
                if "anim" in aset or "animation" in aset or "run" in aset or "runs" in aset:
                    flags.setdefault("anim", True)

    return flags if flags else None

def _should_wait(group_name, is_array_burst, row_flags):
    """
    Decide whether to wait for this group within the row.
    - If row_flags provides explicit bool for group -> use it.
    - Else default: wait only when it's a horizontal array burst.
    """
    if row_flags and group_name in row_flags:
        return bool(row_flags[group_name])
    return bool(is_array_burst)


# ---------------- core ----------------
class PepperScripter(object):
    def __init__(self, controller, verbose=True,**kwargs):
        """
        controller must expose:
          - play_audio(path, async_play=True/False)
          - say(text,   async_play=True/False)
          - play_animation(name, async_play=True/False)
        """
        self.controller = controller
        self.verbose = bool(verbose)

    def run_scene(self, json_path, base=""):
        data = _load_json(json_path, self.verbose)
        if data is None or not isinstance(data, dict) or "scene" not in data or not isinstance(data["scene"], list):
            _log("ERROR", "Invalid JSON scene structure", self.verbose)
            return False
        return self._run_data(data, base, json_path)

    def run_scene_from_file(self, json_path, base=""):
        return self.run_scene(json_path, base=base)

    # -------------- internal --------------
    def _run_data(self, data, base, json_path=""):
        script_name = data.get("script_name", "Unnamed Script")
        audio_source = data.get("audio_source") or data.get("audo_source") or ""
        _log("INFO", "Running script: %s" % script_name, self.verbose)
        if audio_source:
            _log("INFO", "audio_source: %s" % audio_source, self.verbose)

        base_dir = base if base else (os.path.dirname(os.path.abspath(json_path)) if json_path else os.getcwd())
        executed_any = False

        for bi, block in enumerate(data["scene"]):
            if not isinstance(block, dict):
                _log("WARN", "scene[%d] not a dict; skipping" % bi, self.verbose)
                continue

            # PRE wait for block
            pre = _to_float(block.get("wait", block.get("time", 0.0)), 0.0, "scene[%d].wait/time" % bi)
            if pre > 0:
                _log("INFO", "Sleeping %.3fs before block %d" % (pre, bi), self.verbose)
                try:
                    time.sleep(pre)
                except Exception as e:
                    _log("WARN", "time.sleep failed: %s | %s" % (e.__class__.__name__, e), self.verbose)

            rows = block.get("actions") or []
            if not isinstance(rows, list) or not rows:
                _log("WARN", "scene[%d] has no 'actions'; skipping" % bi, self.verbose)
                continue

            # Collect ALL futures launched in this block (block barrier)
            block_futures = []

            # Process rows (vertical). No inter-row wait unless user adds 'hold_for' in a row.
            for ri, row in enumerate(rows):
                if not isinstance(row, dict):
                    _log("WARN", "scene[%d].actions[%d] not a dict; skipping" % (bi, ri), self.verbose)
                    continue

                row_flags = _parse_await_policy(row)

                # ---- AUDIO ----
                audio_scalars = []
                audio_arrays = []
                for key in ("audiofile", "audiofiles", "audio", "audios"):
                    if key in row and row[key] is not None:
                        v = row[key]
                        if isinstance(v, list):
                            audio_arrays.append(v)
                        else:
                            audio_scalars.append(v)

                # Scalars: async; wait only if overridden by row_flags
                for val in audio_scalars:
                    path = _resolve_audio_path(val, audio_source, base_dir)
                    if not path:
                        continue
                    _log("INFO", "BLOCK %d ROW %d: AUDIO %s" % (bi, ri, path), self.verbose)
                    try:
                        fut = self.controller.play_audio(path, async_play=True)
                        executed_any = True
                        if fut is not None:
                            block_futures.append(fut)
                        if _should_wait("audio", False, row_flags) and hasattr(fut, "value"):
                            fut.value()
                    except Exception as e:
                        _log("ERROR", "play_audio failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                        print(traceback.format_exc())

                # Arrays (horizontal burst): launch all, then wait on all futures
                for arr in audio_arrays:
                    futures = []
                    for val in arr:
                        path = _resolve_audio_path(val, audio_source, base_dir)
                        if not path:
                            continue
                        _log("INFO", "BLOCK %d ROW %d: AUDIO %s" % (bi, ri, path), self.verbose)
                        try:
                            fut = self.controller.play_audio(path, async_play=True)
                            executed_any = True
                            if fut is not None:
                                futures.append(fut)
                                block_futures.append(fut)
                        except Exception as e:
                            _log("ERROR", "play_audio failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                            print(traceback.format_exc())
                    if _should_wait("audio", True, row_flags):
                        for fut in futures:
                            try:
                                if hasattr(fut, "value"):
                                    fut.value()
                            except Exception as e:
                                _log("WARN", "audio future error: %s | %s" % (e.__class__.__name__, e), self.verbose)

                # ---- TTS ----
                tts_scalars = []
                tts_arrays = []
                for key in ("say", "text", "texts"):
                    if key in row and row[key] is not None:
                        v = row[key]
                        if isinstance(v, list):
                            tts_arrays.append(v)
                        else:
                            tts_scalars.append(v)

                for val in tts_scalars:
                    txt = "" if val is None else val
                    _log("INFO", 'BLOCK %d ROW %d: SAY "%s"' % (bi, ri, txt), self.verbose)
                    try:
                        fut = self.controller.say(txt, async_play=True)
                        executed_any = True
                        if fut is not None:
                            block_futures.append(fut)
                        if _should_wait("tts", False, row_flags) and hasattr(fut, "value"):
                            fut.value()
                    except Exception as e:
                        _log("ERROR", "say failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                        print(traceback.format_exc())

                for arr in tts_arrays:
                    futures = []
                    for val in arr:
                        txt = "" if val is None else val
                        _log("INFO", 'BLOCK %d ROW %d: SAY "%s"' % (bi, ri, txt), self.verbose)
                        try:
                            fut = self.controller.say(txt, async_play=True)
                            executed_any = True
                            if fut is not None:
                                futures.append(fut)
                                block_futures.append(fut)
                        except Exception as e:
                            _log("ERROR", "say failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                            print(traceback.format_exc())
                    if _should_wait("tts", True, row_flags):
                        for fut in futures:
                            try:
                                if hasattr(fut, "value"):
                                    fut.value()
                            except Exception as e:
                                _log("WARN", "tts future error: %s | %s" % (e.__class__.__name__, e), self.verbose)

                # ---- ANIMATION ----
                anim_scalars = []
                anim_arrays = []
                for key in ("animation", "animations", "run", "runs"):
                    if key in row and row[key] is not None:
                        v = row[key]
                        if isinstance(v, list):
                            anim_arrays.append(v)
                        else:
                            anim_scalars.append(v)

                for val in anim_scalars:
                    name = val
                    if not name:
                        continue
                    _log("INFO", "BLOCK %d ROW %d: ANIMATION %s" % (bi, ri, name), self.verbose)
                    try:
                        fut = self.controller.play_animation(name, async_play=True)
                        executed_any = True
                        if fut is not None:
                            block_futures.append(fut)
                        if _should_wait("anim", False, row_flags) and hasattr(fut, "value"):
                            fut.value()
                    except Exception as e:
                        _log("ERROR", "play_animation failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                        print(traceback.format_exc())

                for arr in anim_arrays:
                    futures = []
                    for name in arr:
                        if not name:
                            continue
                        _log("INFO", "BLOCK %d ROW %d: ANIMATION %s" % (bi, ri, name), self.verbose)
                        try:
                            fut = self.controller.play_animation(name, async_play=True)
                            executed_any = True
                            if fut is not None:
                                futures.append(fut)
                                block_futures.append(fut)
                        except Exception as e:
                            _log("ERROR", "play_animation failed: %s | %s" % (e.__class__.__name__, e), self.verbose)
                            print(traceback.format_exc())
                    if _should_wait("anim", True, row_flags):
                        for fut in futures:
                            try:
                                if hasattr(fut, "value"):
                                    fut.value()
                            except Exception as e:
                                _log("WARN", "anim future error: %s | %s" % (e.__class__.__name__, e), self.verbose)

                # Optional beat between rows
                hold = _to_float(row.get("hold_for", 0.0), 0.0, "scene[%d].actions[%d].hold_for" % (bi, ri))
                if hold > 0:
                    _log("INFO", "Holding %.3fs after row %d in block %d" % (hold, ri, bi), self.verbose)
                    time.sleep(hold)

            # ---- BLOCK BARRIER: wait for all futures in this block ----
            for fut in block_futures:
                try:
                    if hasattr(fut, "value"):
                        fut.value()
                except Exception as e:
                    _log("WARN", "block future error: %s | %s" % (e.__class__.__name__, e), self.verbose)

        if executed_any:
            _log("INFO", "Script complete: %s" % script_name, self.verbose)
        else:
            _log("WARN", "No actions executed.", self.verbose)
        return executed_any


# ------------- optional demo -------------
if __name__ == "__main__":
    # Uses your real controller; edit IP/port if needed
    try:
        from controller import PepperController
    except Exception as e:
        print("[ERROR] Could not import PepperController from pepper_core: %s" % str(e))
        raise SystemExit(1)

    try:
        ctrl = PepperController(ip="192.168.1.8", port=9559, verbose=True)
    except Exception as e:
        print("[ERROR] Failed to initialize PepperController: %s" % str(e))
        raise SystemExit(1)

    demo = {
  "script_name": "DemoScript",
  "audio_source": "/home/nao/.local/share/wav/Vicky_Pepper_Project_2025/Informal Conditions/English/Informal English_Formatted/",
  "scene": [
    {
      "actions": [
        { "audiofile": "1_Informal English.wav" },
        { "animation": "animations/Stand/Gestures/Hey_4" }
      ]
    },
    {
      "actions": [
        { "audiofile": "2_Informal English.wav" },
        { "animation": "animations/Stand/Gestures/ShowSky_5", "await": "anim" },
        { "animation": "animations/Stand/Gestures/Explain_4", "await": "anim" },
        { "animation": "animations/Stand/Gestures/Explain_5", "await": "anim" }
      ]
    },
    {
      "wait": 2.3,
      "actions": [
        { "audiofile": "greeting.wav" },
        { "say": "This was a simple test.", "await": "tts" }
      ]
    }
  ]
}
    try:
        PepperScripter(ctrl, verbose=True)._run_data(demo, base=os.getcwd())
    except Exception as e:
        print("[ERROR] Demo run failed: %s" % str(e))
        print(traceback.format_exc())
        raise SystemExit(1)

