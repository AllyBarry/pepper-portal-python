# -*- coding: utf-8 -*-
import argparse
import os
import sys

# src/ on the path so `import robot` works when run by hand too.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import robot  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default=os.environ.get("PEPPER_IP", "192.168.1.8"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PEPPER_PORT", "9559")))
    parser.add_argument("--scene", required=True, help="Path to JSON scene file")
    parser.add_argument("--quiet", action="store_true")
    # Accepted (ignored) so the portal's generic --lang flag doesn't error.
    parser.add_argument("--lang", "--language", dest="lang", default=None)
    args = parser.parse_args()

    print("[Main] Starting Pepper scene runner...")
    robot.run_scene_file(robot.connect(args.ip, args.port), args.scene, verbose=not args.quiet)
    print("[Main] Scene finished.")
