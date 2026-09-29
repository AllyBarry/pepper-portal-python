# scripts/example_wave.py
from __future__ import print_function
import os, sys, argparse, time

# src/ on the path so `import robot` works when run by hand too.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import robot  # noqa: E402

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default=os.environ.get("PEPPER_IP", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PEPPER_PORT", "9559")))
    # Accepted (ignored) so the portal's generic --lang flag doesn't error.
    parser.add_argument("--lang", "--language", dest="lang", default=None)
    args = parser.parse_args()

    pepper = robot.connect(args.ip, args.port)
    print("Running Hey_1 ...")
    pepper.motion.run_animation("animations/Stand/Gestures/Hey_1")
    print("Done.")

if __name__ == "__main__":
    main()
