"""The loop that ties it together.

    python -m nudge.service            # on the device
    python -m nudge.service --dev      # anywhere: type lines, blank line = click, printed output

Events:
  click   -> resolve the stall, show + say three words
  double  -> three more (excluding what he's seen)
  long    -> repeat the current three
  tap(i)  -> (from the screen) say word i again, mark it as used, add to lexicon
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time

from . import config
from .button import Button
from .lexicon import Lexicon
from .log import StallLog
from .resolver import Resolver, Result
from .ring import RingBuffer

log = logging.getLogger("nudge")


class Nudge:
    def __init__(self, cfg: config.Section, dev: bool = False):
        self.cfg = cfg
        self.dev = dev
        self.ring = RingBuffer(cfg.ring.seconds or 60, cfg.ring.tail_seconds or 6)
        self.lexicon = Lexicon()
        self.stall_log = StallLog(cfg.log.path or "logs/stalls.csv", bool(cfg.log.enabled))
        self.current: Result | None = None
        self.seen: list[str] = []
        self.more_count = 0
        self._busy = threading.Lock()
        self.ui = None          # set by the screen server if running

        if dev:
            from .listener import TypedListener
            from .speak import PrintSpeaker
            from .resolver import LlamaBackend
            self.listener = TypedListener(self.ring)
            self.speaker = PrintSpeaker()
            backend = LlamaBackend(cfg.model.path, n_ctx=cfg.model.n_ctx or 4096,
                                   n_gpu_layers=cfg.model.n_gpu_layers if cfg.model.n_gpu_layers is not None else -1,
                                   n_threads=cfg.model.n_threads, max_tokens=cfg.model.max_tokens or 24,
                                   temperature=cfg.model.temperature or 0.2)
        else:
            from .listener import WhisperStreamListener
            from .speak import Speaker
            from .button import EvdevButton
            from .resolver import LlamaBackend
            self.listener = WhisperStreamListener(
                self.ring, model_path=str(config.ROOT / "models" / f"ggml-{cfg.whisper.model or 'small.en'}.bin"),
                step_ms=int((cfg.whisper.chunk_seconds or 1.0) * 1000),
                capture_device=cfg.whisper.capture_device, language=cfg.whisper.language or "en")
            self.speaker = Speaker(voice=cfg.tts.voice or "en_US-lessac-medium", gap_ms=cfg.tts.gap_ms or 350,
                                   voices_dir=str(config.ROOT / "models" / "piper"))
            self.hw_button = EvdevButton(cfg.button.device_name or "XIAO")
            backend = LlamaBackend(cfg.model.path, n_ctx=cfg.model.n_ctx or 4096,
                                   n_gpu_layers=-1, n_threads=cfg.model.n_threads,
                                   max_tokens=cfg.model.max_tokens or 24,
                                   temperature=cfg.model.temperature or 0.2)
        self.resolver = Resolver(backend, self.lexicon, candidates=cfg.model.candidates or 3)
        Button.on(self.on_button)

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        log.info("warming the prefix cache")
        self.resolver.resolve("hello", "hello")
        self.listener.start()
        if not self.dev:
            self.hw_button.start()
        self._set_status("listening")
        log.info("ready")

    def stop(self) -> None:
        self.listener.stop()
        if not self.dev:
            self.hw_button.stop()
        self.speaker.stop()

    # ---- events ----------------------------------------------------------

    def on_button(self, event: str) -> None:
        if event == "click":
            self.nudge(more=False)
        elif event == "double":
            self.nudge(more=True)
        elif event == "long":
            self.repeat()

    def nudge(self, more: bool) -> None:
        if not self._busy.acquire(blocking=False):
            return                                  # already resolving; ignore the bounce
        try:
            context, tail = self.ring.snapshot()
            if not tail.strip():
                log.info("click with nothing heard")
                self._show([])
                self.speaker.say("say a little more, then press again")
                return
            if not more:
                self.seen = []
                self.more_count = 0
            else:
                self.more_count += 1
            self._set_status("thinking")
            t0 = time.perf_counter()
            result = self.resolver.resolve(context, tail, exclude=self.seen or None)
            self.seen.extend(result.words)
            self.current = result
            ms = (time.perf_counter() - t0) * 1000
            log.info("stall %r -> %s (%.0f ms, more=%d)", tail[-60:], result.words, ms, self.more_count)
            self.stall_log.record(tail, result.words, ms, self.more_count)
            self._show(result.words)
            if result.words:
                self.speaker.say_words(result.words)
            else:
                self.speaker.say("say a little more")
            self._set_status("listening")
        finally:
            self._busy.release()

    def repeat(self) -> None:
        if self.current and self.current.words:
            self.speaker.say_words(self.current.words)

    def tap(self, index: int) -> None:
        """He tapped a card: say it, count it as used, learn it."""
        if not self.current or index >= len(self.current.words):
            return
        word = self.current.words[index]
        self.speaker.say(word)
        self.stall_log.mark_used(word)
        self.lexicon.confirm(word)
        self.resolver.refresh_lexicon()
        self._set_status("listening")

    def heard_after_nudge(self, text: str) -> None:
        """Called by the listener when he says one of the candidates right after a nudge."""
        if not self.current:
            return
        said = {w.strip(".,!?").lower() for w in text.split()}
        for w in self.current.words:
            if w.lower() in said:
                self.stall_log.mark_used(w)
                self.lexicon.confirm(w)
                self.resolver.refresh_lexicon()
                break

    # ---- ui --------------------------------------------------------------

    def _show(self, words: list[str]) -> None:
        if self.ui:
            self.ui.show_words(words)
        else:
            print("  ".join(f"[ {w} ]" for w in words) or "[ say more ]")

    def _set_status(self, status: str) -> None:
        if self.ui:
            self.ui.set_status(status)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true", help="typed input, printed output, no hardware")
    ap.add_argument("--no-ui", action="store_true", help="don't start the screen server")
    ap.add_argument("--settings", help="path to settings.yaml")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cfg = config.load(args.settings)
    app = Nudge(cfg, dev=args.dev)
    if not args.no_ui:
        from .screen import ScreenServer
        app.ui = ScreenServer(app, port=cfg.ui.port or 8765)
        app.ui.start()
    app.start()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        while not stop.is_set():
            stop.wait(1.0)
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
