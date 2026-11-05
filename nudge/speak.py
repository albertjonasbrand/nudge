"""Say the candidates out loud with Piper, through the speaker.

Piper is fast enough (~0.1 s for three words on the Jetson CPU) that we
synthesize on demand. Common phrases are cached in RAM after first use.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading

log = logging.getLogger(__name__)


class Speaker:
    def __init__(self, voice: str = "en_US-lessac-medium", gap_ms: int = 350,
                 piper_bin: str = "piper", play_cmd: list[str] | None = None,
                 voices_dir: str = "models/piper"):
        self.voice = voice
        self.gap_ms = gap_ms
        self.piper = shutil.which(piper_bin) or piper_bin
        self.voices_dir = voices_dir
        # aplay reads raw 16-bit mono at the voice's sample rate (22050 for *-medium)
        self.play_cmd = play_cmd or ["aplay", "-q", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-"]
        self._cache: dict[str, bytes] = {}
        self._lock = threading.Lock()
        self._current: subprocess.Popen | None = None

    def _synth(self, text: str) -> bytes:
        if text in self._cache:
            return self._cache[text]
        model = f"{self.voices_dir}/{self.voice}.onnx"
        out = subprocess.run([self.piper, "--model", model, "--output-raw"],
                             input=text.encode(), capture_output=True, check=True).stdout
        if len(self._cache) < 500:
            self._cache[text] = out
        return out

    def _silence(self, ms: int) -> bytes:
        return b"\x00" * int(22050 * 2 * ms / 1000)

    def say_words(self, words: list[str]) -> None:
        """Speak the candidates in order with a short gap, interrupting anything playing."""
        self.stop()
        pcm = b"".join(self._synth(w) + self._silence(self.gap_ms) for w in words)
        self._play(pcm)

    def say(self, text: str) -> None:
        self.stop()
        self._play(self._synth(text))

    def _play(self, pcm: bytes) -> None:
        with self._lock:
            self._current = subprocess.Popen(self.play_cmd, stdin=subprocess.PIPE)
            proc = self._current

        def feed():
            try:
                proc.stdin.write(pcm)
                proc.stdin.close()
            except BrokenPipeError:
                pass

        threading.Thread(target=feed, daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            if self._current and self._current.poll() is None:
                self._current.kill()
            self._current = None


class PrintSpeaker:
    """Dev stand-in: prints instead of speaking."""

    def say_words(self, words: list[str]) -> None:
        print("🔊", " … ".join(words))

    def say(self, text: str) -> None:
        print("🔊", text)

    def stop(self) -> None:
        pass
