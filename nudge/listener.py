"""Streaming speech-to-text from the mic into the ring buffer.

Runs whisper.cpp's `whisper-stream` as a subprocess (CUDA build on the Jetson)
and pushes each finalized line into the RingBuffer. Audio never touches disk;
whisper-stream reads the mic and emits text on stdout.

On a machine without whisper.cpp, `TypedListener` lets you feed lines by
hand for testing.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time

from .ring import RingBuffer

log = logging.getLogger(__name__)

# whisper-stream prints lines like "[00:00:03.000 --> 00:00:05.000]  hello there"
# or with --no-timestamps just the text; strip anything in brackets to be safe.
_BRACKETS = re.compile(r"\[[^\]]*\]")
_NOISE = re.compile(r"\((?:[^)]*)\)|\*[^*]*\*")   # "(silence)", "*music*"


class WhisperStreamListener:
    def __init__(self, ring: RingBuffer, model_path: str, binary: str = "whisper-stream",
                 step_ms: int = 1000, length_ms: int = 6000, keep_ms: int = 300,
                 capture_device: int | None = None, threads: int = 4, language: str = "en"):
        self.ring = ring
        self.model_path = model_path
        self.binary = shutil.which(binary) or binary
        self.step_ms = step_ms
        self.length_ms = length_ms
        self.keep_ms = keep_ms
        self.capture_device = capture_device
        self.threads = threads
        self.language = language
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_text_at: float = 0.0

    def _cmd(self) -> list[str]:
        cmd = [self.binary, "-m", self.model_path,
               "--step", str(self.step_ms), "--length", str(self.length_ms),
               "--keep", str(self.keep_ms), "-t", str(self.threads),
               "-l", self.language, "--no-timestamps"]
        if self.capture_device is not None:
            cmd += ["-c", str(self.capture_device)]
        return cmd

    def start(self) -> None:
        self._stop.clear()
        self._proc = subprocess.Popen(self._cmd(), stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._thread = threading.Thread(target=self._pump, daemon=True, name="whisper-pump")
        self._thread.start()
        log.info("whisper-stream started: %s", " ".join(self._cmd()))

    def _pump(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            text = _NOISE.sub("", _BRACKETS.sub("", line)).strip()
            if not text or text.lower() in ("you", "thank you", "thanks for watching"):
                continue        # whisper's silence hallucinations
            self.ring.push(text)
            self.last_text_at = time.monotonic()

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None


class TypedListener:
    """Dev stand-in: type lines at the terminal, they go into the ring buffer."""

    def __init__(self, ring: RingBuffer):
        self.ring = ring
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_text_at: float = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="typed-listener")
        self._thread.start()
        print("type what he says, one line at a time; blank line = click")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                line = input()
            except EOFError:
                break
            if line.strip():
                self.ring.push(line)
                self.last_text_at = time.monotonic()
            else:
                from .button import Button
                Button.fire("click")

    def stop(self) -> None:
        self._stop.set()
