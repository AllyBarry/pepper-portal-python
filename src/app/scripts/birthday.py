# -*- coding: utf-8 -*-
# scripts/birthday.py
"""
Fun birthday sequence for Pepper using installed behaviors/animations.
Triggered from the web portal - receives --ip/--port; name comes via
BIRTHDAY_NAME env var (set by the portal's "Name" field).
"""
from __future__ import print_function
import os, argparse, qi, random


DANCE_BEHAVIOR = "dancesequence-20054b/behavior_1"


def run_anim(anim, path):
    """Run an animation synchronously; swallow errors so the sequence continues."""
    try:
        print("  anim:", path)
        anim.run(path)
    except Exception as e:
        print("  (skipped %s: %s)" % (path, e))


def say(tts, text):
    print("  say:", text)
    try:
        tts.say(text)
    except Exception as e:
        print("  (tts failed: %s)" % (e,))


def say_async(tts, text):
    print("  say (async):", text)
    try:
        return tts.say(text, _async=True)
    except Exception as e:
        print("  (tts failed: %s)" % (e,))
        return None


def wait(future):
    if future is None:
        return
    try:
        future.value()
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default=os.environ.get("PEPPER_IP", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PEPPER_PORT", "9559"))
    )
    parser.add_argument(
        "--name",
        type=str,
        default=os.environ.get("BIRTHDAY_NAME", ""),
    )
    # Accepted (ignored) so the portal's generic --lang flag doesn't error.
    parser.add_argument("--lang", "--language", dest="lang", default=None)
    args = parser.parse_args()

    name = (args.name or "").strip()
    addressee = (" " + name) if name else ""

    sess = qi.Session()
    sess.connect("tcp://%s:%d" % (args.ip, args.port))

    tts = sess.service("ALTextToSpeech")
    anim = sess.service("ALAnimationPlayer")
    motion = sess.service("ALMotion")
    try:
        bm = sess.service("ALBehaviorManager")
    except Exception:
        bm = None

    # Make sure motors are on for the gestures.
    try:
        if not motion.robotIsWakeUp():
            print("Waking up Pepper...")
            motion.wakeUp()
    except Exception:
        pass

    # 1. Grand entrance — wave + greeting
    print("Step 1: entrance")
    fut = say_async(tts, "Hey%s! Come here, come here!" % addressee)
    run_anim(anim, "animations/Stand/Gestures/Hey_1")
    run_anim(anim, "animations/Stand/Gestures/ComeOn_1")
    wait(fut)

    # 2. Build excitement — "I have news!"
    print("Step 2: excitement")
    fut = say_async(tts, "I have something amazing to tell you!")
    run_anim(anim, "animations/Stand/Emotions/Positive/Excited_1")
    wait(fut)
    run_anim(anim, "animations/LED/CircleEyes")

    # 3. Countdown
    print("Step 3: countdown")
    say(tts, "Are you ready? On the count of three!")
    for n, n_anim in (
        ("Three!", "animations/Stand/Gestures/CountThree_1"),
        ("Two!", "animations/Stand/Gestures/CountTwo_1"),
        ("One!", "animations/Stand/Gestures/CountOne_1"),
    ):
        fut = say_async(tts, n)
        run_anim(anim, n_anim)
        wait(fut)

    # 4. The main birthday moment
    print("Step 4: birthday reveal")
    fut = say_async(tts, "Happy birthday%s!" % addressee)
    run_anim(anim, "animations/Stand/Waiting/HappyBirthday_1")
    wait(fut)

    # 5. The tune — Bandmaster stands in for a trumpet fanfare
    print("Step 5: fanfare")
    fut = say_async(tts, "And now, a tune in your honor!")
    run_anim(anim, "animations/Stand/Waiting/Bandmaster_1")
    wait(fut)

    # 6. Dance finale (installed Choregraphe behavior, if present)
    if bm is not None:
        try:
            if bm.isBehaviorInstalled(DANCE_BEHAVIOR):
                print("Step 6: dance finale -", DANCE_BEHAVIOR)
                say(tts, "Let's dance!")
                bm.runBehavior(DANCE_BEHAVIOR)
            else:
                print("Step 6: dance skipped (%s not installed)" % DANCE_BEHAVIOR)
                # fall back to something fun
                run_anim(anim, "animations/Stand/Waiting/FunnyDancer_1")
        except Exception as e:
            print("Step 6: dance error:", e)

    # 7. Wish + kisses
    print("Step 7: make a wish")
    fut = say_async(tts, "Make a wish%s! And blow out the candles." % addressee)
    run_anim(anim, "animations/Stand/Emotions/Positive/Shy_1")
    wait(fut)
    run_anim(anim, "animations/Stand/Gestures/Kisses_1")

    # 8. Victorious finish
    print("Step 8: finish")
    closers = [
        "animations/Stand/Emotions/Positive/Winner_2",
        "animations/Stand/Emotions/Positive/Proud_2",
        "animations/Stand/Emotions/Positive/Ecstatic_1",
    ]
    fut = say_async(
        tts,
        "Wishing you a year full of joy, laughter, and lots of cake%s!" % addressee,
    )
    run_anim(anim, random.choice(closers))
    wait(fut)
    run_anim(anim, "animations/Stand/Gestures/BowShort_1")

    print("Done.")


if __name__ == "__main__":
    main()
