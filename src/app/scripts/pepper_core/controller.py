import qi


class PepperController:
    def __init__(self, ip="127.0.0.1", port=9559):
        print(f"[PepperController] Connecting to {ip}:{port}...")
        self.session = qi.Session()
        self.session.connect(f"tcp://{ip}:{port}")

        print("[PepperController] Connected. Initializing services...")
        self.audio = self.session.service("ALAudioPlayer")
        self.anim = self.session.service("ALAnimationPlayer")
        self.tts = self.session.service("ALTextToSpeech")
        self.posture = self.session.service("ALRobotPosture")
        print("[PepperController] Services ready.")

    def say(self, text, async_play=False):
        if not isinstance(text, str):
            print("[Warning] say() received non-string text")
            return
        print(f"[PepperController] Speaking: {text}")
        if async_play:
            self.tts.post.say(text)
        else:
            self.tts.say(text)

    def play_audio(self, path, async_play=False):
        if not path.endswith(".m4a"):
            print(f"[Warning] Audio file {path} does not appear to be a .m4a file")
        print(f"[PepperController] Playing audio: {path}")
        file_id = self.audio.loadFile(path)
        if async_play:
            self.audio.post.play(file_id)
        else:
            self.audio.play(file_id)

    def play_animation(self, animation_name, async_play=False):
        if not isinstance(animation_name, str):
            print("[Warning] play_animation() received invalid animation name")
            return
        print(f"[PepperController] Running animation: {animation_name}")
        if async_play:
            self.anim.post.run(animation_name)
        else:
            self.anim.run(animation_name)

    def set_posture(self, posture_name="StandInit"):
        print(f"[PepperController] Setting posture to: {posture_name}")
        self.posture.goToPosture(posture_name, 0.8)
