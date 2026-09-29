# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import unittest

from fakes import FakeFuture

from pepper_core import media_store
from robot.scenes import SceneRunner


class FakeRobotFiles(object):
    def __init__(self, remote):
        self.remote = remote
        self.pushed = []
        self.deleted = []

    def list(self):
        return dict(self.remote)

    def make_dirs(self, rels):
        pass

    def push(self, local_path, rel, mtime):
        self.pushed.append(rel)

    def delete(self, rel):
        self.deleted.append(rel)


class MediaStoreTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved_root = media_store.MEDIA_ROOT
        self._saved_files = media_store._files
        media_store.MEDIA_ROOT = self.root
        self.fake = FakeRobotFiles(remote={"old/pepper_only.wav": (1, 1)})
        media_store._files = lambda ip: self.fake
        with media_store._state.lock:
            media_store._state.ip = "10.0.0.2"
            media_store._state.remote = None
            media_store._state.errors = {}
        for rel in ("uploads/hello.wav", "video/tour.mp4", "img/logo.png"):
            path = os.path.join(self.root, *rel.split("/"))
            os.makedirs(os.path.dirname(path))
            with open(path, "wb") as f:
                f.write(b"x" * 10)

    def tearDown(self):
        media_store.MEDIA_ROOT = self._saved_root
        media_store._files = self._saved_files
        shutil.rmtree(self.root)

    def test_only_audio_is_pushed(self):
        media_store._sync_pass()
        self.assertEqual(self.fake.pushed, ["uploads/hello.wav"])

    def test_status_marks_video_and_images_as_jetson_only(self):
        media_store._sync_pass()
        states = dict((f["path"], (f["state"], f["kind"])) for f in media_store.status()["files"])
        self.assertEqual(states["video/tour.mp4"], ("jetson_only", "video"))
        self.assertEqual(states["img/logo.png"], ("jetson_only", "image"))
        self.assertEqual(states["uploads/hello.wav"], ("synced", "audio"))
        self.assertEqual(states["old/pepper_only.wav"][0], "pepper_only")

    def test_deleting_a_video_never_touches_pepper(self):
        self.assertIsNone(media_store.delete_file("video/tour.mp4"))
        self.assertEqual(self.fake.deleted, [])
        media_store.delete_file("uploads/hello.wav")
        self.assertEqual(self.fake.deleted, ["uploads/hello.wav"])


class FakePerformer(object):
    def __init__(self):
        self.calls = []

    def _rec(self, kind, value, async_play):
        self.calls.append((kind, value))
        return FakeFuture()

    def play_audio(self, path, async_play=True):
        return self._rec("audio", path, async_play)

    def say(self, text, async_play=True):
        return self._rec("say", text, async_play)

    def play_animation(self, name, async_play=True):
        return self._rec("anim", name, async_play)

    def play_behavior(self, name, async_play=True):
        return self._rec("behavior", name, async_play)


class SceneRunnerTest(unittest.TestCase):
    def test_runs_rows_and_resolves_bare_audio_to_uploads(self):
        performer = FakePerformer()
        ran = SceneRunner(performer, verbose=False)._run_data({"scene": [
            {"actions": [{"audiofile": "hi.wav"}, {"say": "Hello", "animation": "a/b"}]},
        ]}, base="")
        self.assertTrue(ran)
        self.assertEqual(performer.calls, [
            ("audio", "/data/home/nao/.local/share/wav/uploads/hi.wav"),
            ("say", "Hello"),
            ("anim", "a/b"),
        ])


if __name__ == "__main__":
    unittest.main()
