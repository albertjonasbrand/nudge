"""Turn a stall into three candidate words.

Backends implement `complete(system, user) -> str`. The llama.cpp backend keeps
the system prompt (with the lexicon) in its prefix cache so a click only pays
for the user turn.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from . import phono
from . import prompt as P
from .lexicon import Lexicon

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*(?: [A-Za-z][A-Za-z'\-]*)?")
_STRIP_RE = re.compile(r"^[\s\d\.\)\-\*•:]+|[\s\.\,\!\?]+$")


class Backend(Protocol):
    def complete(self, system: str, user: str) -> str: ...


@dataclass
class Result:
    words: list[str]
    raw: str
    ms: float
    context: str
    tail: str
    extra: dict = field(default_factory=dict)


class Resolver:
    def __init__(self, backend: Backend, lexicon: Lexicon | None = None, candidates: int = 3,
                 sound_hints: bool = True):
        self.backend = backend
        self.lexicon = lexicon or Lexicon()
        self.candidates = candidates
        self.sound_hints = sound_hints
        self._lex_text = self.lexicon.as_prompt_text()

    def refresh_lexicon(self) -> None:
        self.lexicon.load()
        self._lex_text = self.lexicon.as_prompt_text()

    def resolve(self, context: str, tail: str, exclude: list[str] | None = None) -> Result:
        hints = phono.hints_for(tail) if self.sound_hints else ""
        system, user = P.build(context, tail, self._lex_text, hints)
        if exclude:
            user = user.replace("\nAnswer:", "\nNot these, he rejected them: " + ", ".join(exclude) + "\n\nAnswer:")
        t0 = time.perf_counter()
        raw = self.backend.complete(system, user)
        ms = (time.perf_counter() - t0) * 1000
        # words he already said are never the missing word (unless they're in his lexicon,
        # e.g. he said "Mayo" correctly and we just confirm it)
        said = {w.strip(".,!?\"'").lower() for w in (context + " " + tail).split()}
        said -= self.lexicon.all_words()
        words = parse_words(raw, self.candidates, list(exclude or []) + sorted(said))
        return Result(words=words, raw=raw, ms=ms, context=context, tail=tail)


def parse_words(raw: str, n: int, exclude: list[str]) -> list[str]:
    """Pull up to n distinct words from the model's reply, in order."""
    seen: set[str] = {e.lower() for e in exclude}
    out: list[str] = []
    for line in raw.splitlines():
        line = _STRIP_RE.sub("", line).strip()
        if not line:
            continue
        m = _WORD_RE.search(line)
        if not m:
            continue
        w = m.group(0).strip()
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
        if len(out) == n:
            break
    return out


class LlamaBackend:
    """llama.cpp via llama-cpp-python. Prefix caching is on by default in the
    chat path as long as the system prompt is byte-identical between calls."""

    def __init__(self, model_path: str, n_ctx: int = 4096, n_gpu_layers: int = -1,
                 n_threads: int | None = None, max_tokens: int = 24, temperature: float = 0.2):
        from llama_cpp import Llama  # imported lazily so the harness can run other backends

        self.llm = Llama(model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers,
                         n_threads=n_threads, verbose=False)
        self.max_tokens = max_tokens
        self.temperature = temperature

    def complete(self, system: str, user: str) -> str:
        out = self.llm.create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stop=["\n\n", "CONVERSATION"],
        )
        return out["choices"][0]["message"]["content"]
