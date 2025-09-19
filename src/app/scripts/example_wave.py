# scripts/example_wave.py
from __future__ import print_function
import os, argparse, qi, time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default=os.environ.get("PEPPER_IP", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PEPPER_PORT", "9559")))
    args = parser.parse_args()

    sess = qi.Session()
    sess.connect("tcp://%s:%d" % (args.ip, args.port))
    anim = sess.service("ALAnimationPlayer")
    print("Running Hey_1 ...")
    anim.run("animations/Stand/Gestures/Hey_1")
    print("Done.")

if __name__ == "__main__":
    main()
