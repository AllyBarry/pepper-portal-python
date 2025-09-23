# scripts/example_wave.py
from __future__ import print_function
import os, argparse, qi, time

HOME_AUDIO_PATH = "/data/home/nao/.local/share/wav/"

audio_files = {
    "English": {
        "1": "Vicky_Pepper_Project_2025/Informal Conditions/English/Informal English_Formatted/1_Informal English.wav",
        "2": "Vicky_Pepper_Project_2025/Informal Conditions/English/Informal English_Formatted/2_Informal English.wav",
        "3": "Vicky_Pepper_Project_2025/Informal Conditions/English/Informal English_Formatted/3_Informal English.wav",
        "4": "Vicky_Pepper_Project_2025/Informal Conditions/English/Informal English_Formatted/4_Informal English.wav",
        "5": "Vicky_Pepper_Project_2025/Informal Conditions/English/Informal English_Formatted/5_Informal English.wav",
        "6": "Vicky_Pepper_Project_2025/Informal Conditions/English/Informal English_Formatted/6_Informal English.wav",
    },
    "IsiZulu": {
        "1": "Vicky_Pepper_Project_2025/Informal Conditions/IsiZulu/Informal Zulu_Format/1_Informal Zulu.wav",
        "2": "Vicky_Pepper_Project_2025/Informal Conditions/IsiZulu/Informal Zulu_Format/2_Informal Zulu.wav",
        "3": "Vicky_Pepper_Project_2025/Informal Conditions/IsiZulu/Informal Zulu_Format/3_Informal Zulu.wav",
        "4": "Vicky_Pepper_Project_2025/Informal Conditions/IsiZulu/Informal Zulu_Format/4_Informal Zulu.wav",
        "5": "Vicky_Pepper_Project_2025/Informal Conditions/IsiZulu/Informal Zulu_Format/5_Informal Zulu.wav",
        "6": "Vicky_Pepper_Project_2025/Informal Conditions/IsiZulu/Informal Zulu_Format/6_Informal Zulu.wav",
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default=os.environ.get("PEPPER_IP", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PEPPER_PORT", "9559"))
    )
    parser.add_argument("--language", type=str, default=os.environ.get("SCRIPT_LANG", "English"))
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
    anim.run("animations/Stand/Gestures/Hey_4")
    # wait the end of the audio
    future.value()

    # Audio File #2
    print("Playing Audio File 2...")
    future = audio_player_service.play(audio2, _async=True)
    anim.run("animations/Stand/Gestures/ShowSky_5")
    anim.run("animations/Stand/Gestures/Explain_4")
    anim.run("animations/Stand/Gestures/Explain_5")
    # wait the end of the audio
    future.value()

    # Audio File #3
    future = audio_player_service.play(audio3, _async=True)
    anim.run("animations/Stand/Gestures/Give_5")
    anim.run("animations/Stand/Gestures/Give_3")
    anim.run("animations/Stand/Gestures/Give_4")
    anim.run("animations/Stand/Gestures/Enthusiastic_5")
    # wait the end of the audio
    future.value()

    # Audio File #4
    future = audio_player_service.play(audio4, _async=True)
    anim.run("animations/Stand/Gestures/Explain_8")
    anim.run("animations/Stand/Gestures/Explain_11")
    anim.run("animations/Stand/Gestures/Thinking_1")
    anim.run("animations/Stand/Gestures/Explain_3")
    # wait the end of the audio
    future.value()

    # Audio File #5
    future = audio_player_service.play(audio5, _async=True)
    anim.run("animations/Stand/Gestures/Explain_8")
    anim.run("animations/Stand/Gestures/Give_3")
    anim.run("animations/Stand/Gestures/Explain_11")
    # wait the end of the audio
    future.value()

    # Audio File #6
    future = audio_player_service.play(audio6, _async=True)
    anim.run("animations/Stand/Gestures/Explain_8")
    # wait the end of the audio
    future.value()

    print("Done.")


if __name__ == "__main__":
    main()
