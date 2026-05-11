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

    time.sleep(1)
    # 2. Play a simple animation
    # 3. Play a test audio file
    #base = "/home/nao/.local/share/wav/Vicky_Pepper_Project_2025/Informal Conditions/English/Informal English_Formatted/"
    base = "/home/nao/.local/share/wav/Vicky_Pepper_Project_2025/Informal Conditions/English/"
    wav_path = "1.wav"
    #kwav_path = "1_Informal English.wav"
    print("Testing audio playback with {}".format(base+wav_path))
    controller.play_audio(base+wav_path, async_play=False)
    print("Testing animation...")
    controller.play_animation("animations/Stand/Gestures/Hey_4", async_play=True)


    print("\nAll basic tests complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="192.168.1.7", help="Pepper robot IP address")
    parser.add_argument("--port", type=int, default=9559, help="Pepper robot port")
    args = parser.parse_args()

    try:
        ctrl = PepperController(ip=args.ip, port=args.port)
        test_all(ctrl)
    except Exception as e:
        print("[ERROR] Could not connect to Pepper or run tests: {}".format(str(e)))

