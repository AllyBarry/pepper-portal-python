import json
import os
import time
from collections import defaultdict


class PepperScripter:
    def __init__(self, controller):
        self.controller = controller

    def run_scene_from_file(self, json_path, base_folder=""):
        if not os.path.exists(json_path):
            print(f"[Error] Scene file not found: {json_path}")
            return

        with open(json_path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"[Error] Failed to parse JSON: {e}")
                return

        script_name = data.get("script_name", "Unnamed Script")
        print(f"[PepperScripter] Running script: {script_name}")
        scene = data.get("scene", [])
        if not isinstance(scene, list):
            print("[Error] 'scene' must be a list.")
            return

        audio_groups = defaultdict(list)
        for event in scene:
            audiofile = event.get("audiofile")
            if not audiofile:
                print("[Warning] Skipping event without 'audiofile'")
                continue
            audio_groups[audiofile].append(event)

        for audiofile, actions in audio_groups.items():
            full_audio_path = os.path.join(base_folder, audiofile)
            if not os.path.exists(full_audio_path):
                print(f"[Warning] Skipping missing audio file: {full_audio_path}")
                continue

            print(f"[PepperScripter] Playing audio file: {audiofile}")
            self.controller.play_audio(full_audio_path, async_play=True)
            start_time = time.time()

            for event in sorted(actions, key=lambda x: x.get("time", 0.0)):
                delay = event.get("time", 0.0) - (time.time() - start_time)
                if delay > 0:
                    time.sleep(delay)

                action = event.get("action")
                if action == "say":
                    text = event.get("text", "")
                    self.controller.say(text, async_play=True)
                elif action == "run":
                    anim = event.get("animation")
                    self.controller.play_animation(anim, async_play=True)
                elif action is None:
                    print("[Warning] Event missing 'action' key")
                else:
                    print(f"[Warning] Unknown action: {action}")
