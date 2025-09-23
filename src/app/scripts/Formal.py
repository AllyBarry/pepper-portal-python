# scripts/example_wave.py
from __future__ import print_function
import os, argparse, qi, time

HOME_AUDIO_PATH = "/data/home/nao/.local/share/wav/"

audio_files = {
    "English": {
        "1": "Vicky_Pepper_Project_2025/Formal Conditions/English/Formal English_Formatted/1_Formal English.wav",
        "2": "Vicky_Pepper_Project_2025/Formal Conditions/English/Formal English_Formatted/2_Formal English.wav",
        "3": "Vicky_Pepper_Project_2025/Formal Conditions/English/Formal English_Formatted/3_Formal English.wav",
        "4": "Vicky_Pepper_Project_2025/Formal Conditions/English/Formal English_Formatted/4_Formal English.wav",
        "5": "Vicky_Pepper_Project_2025/Formal Conditions/English/Formal English_Formatted/5_Formal English.wav",
        "6": "Vicky_Pepper_Project_2025/Formal Conditions/English/Formal English_Formatted/6_Formal English.wav",
    },
    "IsiZulu": {
        "1": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/1_Formal Zulu.wav",
        "2": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/2_Formal Zulu.wav",
        "3": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/3_Formal Zulu.wav",
        "4": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/4_Formal Zulu.wav",
        "5": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/5_Formal Zulu.wav",
        "6": "Vicky_Pepper_Project_2025/Formal Conditions/IsiZulu/Formal Zulu_Formatted/6_Formal Zulu.wav",
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default=os.environ.get("PEPPER_IP", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PEPPER_PORT", "9559"))
    )
    parser.add_argument(
        "--language", type=str, default=os.environ.get("SCRIPT_LANG", "English")
    )
    args = parser.parse_args()

    sess = qi.Session()
    sess.connect("tcp://%s:%d" % (args.ip, args.port))
    audio_player_service = sess.service("ALAudioPlayer")
    anim = sess.service("ALAnimationPlayer")

    lang = args.language

    # Pre-load all audios to prevent delays
    print("Loading Audio Files...")
    audio1 = audio_player_service.loadFile(HOME_AUDIO_PATH + audio_files[lang]["1"])
    audio2 = audio_player_service.loadFile(HOME_AUDIO_PATH + audio_files[lang]["2"])
    audio3 = audio_player_service.loadFile(HOME_AUDIO_PATH + audio_files[lang]["3"])
    audio4 = audio_player_service.loadFile(HOME_AUDIO_PATH + audio_files[lang]["4"])
    audio5 = audio_player_service.loadFile(HOME_AUDIO_PATH + audio_files[lang]["5"])
    audio6 = audio_player_service.loadFile(HOME_AUDIO_PATH + audio_files[lang]["6"])

    print("Playing Audio File 1...")
    # Audio File #1
    # play the audio, this will return right away
    future = audio_player_service.play(audio1, _async=True)
    anim.run("animations/Stand/Emotions/Neutral/Embarrassed_1")
    # wait the end of the audio
    future.value()

    # Audio File #2
    print("Playing Audio File 2...")
    future = audio_player_service.play(audio2, _async=True)
    # anim.run("animations/Stand/Emotions/Neutral/Embarrassed_1")
    # wait the end of the audio
    future.value()

    # Audio File #3
    future = audio_player_service.play(audio3, _async=True)
    # anim.run("animations/Stand/Emotions/Neutral/Embarrassed_1")
    # wait the end of the audio
    future.value()

    # Audio File #4
    future = audio_player_service.play(audio4, _async=True)
    # anim.run("animations/Stand/Emotions/Neutral/Embarrassed_1")
    # wait the end of the audio
    future.value()

    # Audio File #5
    future = audio_player_service.play(audio5, _async=True)
    # wait the end of the audio
    future.value()

    # Audio File #6
    future = audio_player_service.play(audio6, _async=True)
    anim.run("animations/Stand/Emotions/Neutral/Embarrassed_1")
    # wait the end of the audio
    future.value()

    print("Done.")


if __name__ == "__main__":
    main()
