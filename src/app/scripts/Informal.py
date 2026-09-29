# scripts/Informal.py
from __future__ import print_function
import os, sys, argparse, time

# src/ on the path so `import robot` works when run by hand too.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import robot  # noqa: E402

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

    pepper = robot.connect(args.ip, args.port)
    audio = pepper.audio
    motion = pepper.motion

    lang = args.language

    # Pre-load all audios to prevent delays
    print("Loading Audio Files...")
    audio1 = audio.load(HOME_AUDIO_PATH + audio_files[lang]["1"])
    audio2 = audio.load(HOME_AUDIO_PATH + audio_files[lang]["2"])
    audio3 = audio.load(HOME_AUDIO_PATH + audio_files[lang]["3"])
    audio4 = audio.load(HOME_AUDIO_PATH + audio_files[lang]["4"])
    audio5 = audio.load(HOME_AUDIO_PATH + audio_files[lang]["5"])
    audio6 = audio.load(HOME_AUDIO_PATH + audio_files[lang]["6"])

    print("Playing Audio File 1...")
    # Audio File #1
    # play the audio, this will return right away
    future = audio.play_loaded(audio1, wait=False)
    motion.run_animation("animations/Stand/Gestures/Hey_4")
    motion.run_animation("animations/Stand/Gestures/Give_3")
    motion.run_animation("animations/Stand/Gestures/Give_5")
    motion.run_animation("animations/Stand/Gestures/Give_3")
    motion.run_animation("animations/Stand/Gestures/Explain_8")
    # wait the end of the audio
    future.value()

    # Audio File #2
    print("Playing Audio File 2...")
    future = audio.play_loaded(audio2, wait=False)
    motion.run_animation("animations/Stand/Gestures/ShowSky_5")
    motion.run_animation("animations/Stand/Gestures/Explain_4")
    motion.run_animation("animations/Stand/Gestures/Explain_5")
    # wait the end of the audio
    future.value()

    # Audio File #3
    future = audio.play_loaded(audio3, wait=False)
    motion.run_animation("animations/Stand/Gestures/Give_5")
    motion.run_animation("animations/Stand/Gestures/Give_3")
    motion.run_animation("animations/Stand/Gestures/Give_4")
    motion.run_animation("animations/Stand/Gestures/Give_3")
    motion.run_animation("animations/Stand/Gestures/Give_3")
    motion.run_animation("animations/Stand/Gestures/Excited_1")
    # motion.run_animation("animations/Stand/Gestures/Enthusiastic_5")
    motion.run_animation("animations/Stand/Gestures/Give_3")
    # wait the end of the audio
    future.value()

    # Audio File #4
    future = audio.play_loaded(audio4, wait=False)
    motion.run_animation("animations/Stand/Gestures/Explain_8")
    motion.run_animation("animations/Stand/Gestures/Explain_11")
    motion.run_animation("animations/Stand/Gestures/Thinking_1")
    motion.run_animation("animations/Stand/Gestures/Explain_3")
    # wait the end of the audio
    future.value()

    # Audio File #5
    future = audio.play_loaded(audio5, wait=False)
    motion.run_animation("animations/Stand/Gestures/Explain_8")
    motion.run_animation("animations/Stand/Gestures/Far_1")
    motion.run_animation("animations/Stand/Gestures/Explain_11")
    motion.run_animation("animations/Stand/Gestures/Give_5")
    motion.run_animation("animations/Stand/Gestures/Thinking_8")
    motion.run_animation("animations/Stand/Gestures/Give_3")
    # wait the end of the audio
    future.value()

    # Audio File #6
    future = audio.play_loaded(audio6, wait=False)
    motion.run_animation("animations/Stand/Gestures/Give_4")
    motion.run_animation("animations/Stand/Gestures/Thinking_8")
    motion.run_animation("animations/Stand/Gestures/Me_7")
    motion.run_animation("animations/Stand/Gestures/YouKnowWhat_5")
    motion.run_animation("animations/Stand/Gestures/Explain_11")
    # wait the end of the audio
    future.value()

    print("Done.")


if __name__ == "__main__":
    main()
