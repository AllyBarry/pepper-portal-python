# -*- coding: utf-8 -*-
import argparse
from pepper_core import *

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="192.168.1.8")
    parser.add_argument("--port", type=int, default=9559)
    parser.add_argument("--scene", required=True, help="Path to JSON scene file")
    parser.add_argument("--base", default="", help="Base folder for audio files")
    parser.add_argument("--async", dest="use_async", action="store_true",
                        help="Run non-blocking on robot (default blocks so events finish)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    print("[Main] Starting Pepper scene runner...")
    ctrl = PepperController(ip=args.ip, port=args.port, verbose=True)
    scripter = PepperScripter(controller=ctrl, blocking=(not args.use_async), verbose=(not args.quiet))
    scripter.run_scene(args.scene, base=args.base)
    print("[Main] Scene finished.")

