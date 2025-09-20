# -*- coding: utf-8 -*-
import argparse

import pepper_core

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="192.168.1.9")
    parser.add_argument("--port", type=int, default=9559)
    parser.add_argument("--scene", required=True, help="Path to JSON scene file")
    parser.add_argument("--base", default="", help="Base folder for audio files")
    args = parser.parse_args()

    print("[Main] Starting Pepper scene runner...")
    controller = PepperController(ip=args.ip, port=args.port)
    scripter = PepperScripter(controller)
    scripter.run_scene_from_file(args.scene, base_folder=args.base)
    print("[Main] Scene finished.")
