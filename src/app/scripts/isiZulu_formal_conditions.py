# scripts/example_wave.py
from __future__ import print_function
import os, argparse, qi, time

HOME_AUDIO_PATH = "/data/home/nao/.local/share/wav/"

audio_files = {
    "1": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/1_Formal Zulu.wav",
    "2": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/2_Formal Zulu.wav",
    "3": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/3_Formal Zulu.wav",
    "4": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/4_Formal Zulu.wav",
    "5": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/5_Formal Zulu.wav",
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default=os.environ.get("PEPPER_IP", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PEPPER_PORT", "9559")))
    args = parser.parse_args()

    sess = qi.Session()
    sess.connect("tcp://%s:%d" % (args.ip, args.port))
    audio_player_service = sess.service("ALAudioPlayer")
    anim = sess.service("ALAnimationPlayer")

    print("Playing Audio File...")
    # fileId = audio_player_service.loadFile(HOME_AUDIO_PATH + audio_files["1"])
    # audio_player_service.play(fileId)
    anim.run("animations/Stand/Emotions/Neutral/Embarrassed_1")
    print("Done.")

if __name__ == "__main__":
    main()
