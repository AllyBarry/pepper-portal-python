# -*- coding: utf-8 -*-
import argparse
import os
import time
from pepper_core import PepperController


def test_all(controller):
    print("Running controller diagnostics...\n")

    # 1. Say something
    print("Testing speech...")
    controller.say("Hello! This is a test of my speech system.", async_play=True)

    # 2. Play a simple animation
    print("Testing animation...")
    controller.play_animation("animations/Stand/Gestures/Hey_4", async_play=False)

    time.sleep(1)

    # 3. Play a test audio file
    wav_path = "test.wav"
    if os.path.exists(wav_path):
        print("Testing audio playback with {}".format(wav_path))
        controller.play_audio(wav_path, async_play=False)
    else:
        print("Skipping audio test. '{}' not found.".format(wav_path))

    print("\nAll basic tests complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="192.168.1.8", help="Pepper robot IP address")
    parser.add_argument("--port", type=int, default=9559, help="Pepper robot port")
    args = parser.parse_args()

    try:
        ctrl = PepperController(ip=args.ip, port=args.port)
        test_all(ctrl)
    except Exception as e:
        print("[ERROR] Could not connect to Pepper or run tests: {}".format(str(e)))

