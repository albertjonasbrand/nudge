"""Sound-alike hints for paraphasia.

When he says "goat" for coat, a language model reasons by meaning (sheep, cow)
unless it is handed what *sounds* like goat. This module builds that list
deterministically from CMUdict and a word-frequency table, so the model gets
"sounds like goat: coat, boat, vote, note, wrote" as a hint.

Two generators, merged and ranked by how common the word is:
- phoneme neighbors: same rhyme, or one phoneme substituted/added/dropped (CMUdict)
- spelling neighbors: one letter substituted/added/dropped (catches words CMUdict
  lacks, like a misheard "barage" -> garage)
"""

from __future__ import annotations

import functools
import re
import string

import pronouncing
from wordfreq import top_n_list, zipf_frequency

VOCAB_SIZE = 30000
MIN_ZIPF = 3.0          # roughly "a word an adult uses"; filters bacote, chipote, bjork
MAX_ZIPF = 5.8          # drops get/got/that/there: function words are never the stalled word
STOP = set("""a an the and or but of to in on at for with is are was were be been it its
he she they we you i me my his her their our this that these those there here uh um
um yeah no not so just like you know thing things stuff one ones get got go going
""".split())
_WORD = re.compile(r"[a-z']+")


@functools.lru_cache(maxsize=1)
def vocab() -> list[str]:
    return [w for w in top_n_list("en", VOCAB_SIZE)
            if w.isalpha() and len(w) >= 3 and MIN_ZIPF <= zipf_frequency(w, "en") <= MAX_ZIPF]


@functools.lru_cache(maxsize=1)
def _by_rhyme() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for w in vocab():
        for ph in pronouncing.phones_for_word(w)[:1]:
            rp = pronouncing.rhyming_part(ph)
            if rp:
                out.setdefault(rp, []).append(w)
    return out


@functools.lru_cache(maxsize=1)
def _by_phones() -> dict[str, str]:
    """phoneme string (stress stripped) -> word, first common spelling wins."""
    out: dict[str, str] = {}
    for w in vocab():
        for ph in pronouncing.phones_for_word(w)[:1]:
            key = _strip_stress(ph)
            out.setdefault(key, w)
    return out


def _strip_stress(ph: str) -> str:
    return re.sub(r"\d", "", ph)


def _phone_edits(phones: list[str]) -> set[str]:
    """All one-phoneme substitutions, deletions, and insertions."""
    out: set[str] = set()
    for i in range(len(phones)):
        out.add(" ".join(phones[:i] + phones[i + 1:]))                     # drop
        for p in _PHONES:
            out.add(" ".join(phones[:i] + [p] + phones[i + 1:]))          # swap
    for i in range(len(phones) + 1):
        for p in _PHONES:
            out.add(" ".join(phones[:i] + [p] + phones[i:]))              # insert
    return out


_PHONES = ("AA AE AH AO AW AY B CH D DH EH ER EY F G HH IH IY JH K L M N NG OW OY "
           "P R S SH T TH UH UW V W Y Z ZH").split()


def _spelling_edits(word: str) -> set[str]:
    letters = string.ascii_lowercase
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    out = {a + b[1:] for a, b in splits if b}
    out |= {a + c + b[1:] for a, b in splits if b for c in letters}
    out |= {a + c + b for a, b in splits for c in letters}
    out.discard(word)
    return out


def sound_alikes(word: str, n: int = 6) -> list[str]:
    """Common words that sound like `word`, most common first."""
    word = word.lower().strip("'")
    if not word or word in STOP or len(word) < 3:
        return []
    rhymes: set[str] = set()
    near: set[str] = set()

    for ph in pronouncing.phones_for_word(word)[:1]:
        rp = pronouncing.rhyming_part(ph)
        rhymes.update(_by_rhyme().get(rp, []))
        table = _by_phones()
        for alt in _phone_edits(_strip_stress(ph).split()):
            w = table.get(alt)
            if w:
                near.add(w)

    vs = set(vocab())
    near.update(e for e in _spelling_edits(word) if e in vs)

    rhymes.discard(word)
    near -= rhymes
    near.discard(word)
    freq = lambda w: -zipf_frequency(w, "en")
    # onset swaps (goat -> coat) are the commonest paraphasia, so exact rhymes lead
    ranked = sorted(rhymes, key=freq)[: max(3, n - 2)] + sorted(near, key=freq)
    out: list[str] = []
    for w in ranked:
        if w not in out:
            out.append(w)
        if len(out) == n:
            break
    return out


_TRAIL = set("""the a an my your his her our their to of for at in on with and or uh um
hmm er like so that this these those it its some any thing things one""".split())


def looks_like_swap(tail: str) -> bool:
    """True when he finished a phrase with a real word (maybe the wrong one),
    False when he trailed off on 'the, uh, the' (that's anomia; hints only distract)."""
    words = _WORD.findall(tail.lower())
    if not words:
        return False
    return words[-1] not in _TRAIL and len(words[-1]) >= 3


def hints_for(tail: str, per_word: int = 8, max_words: int = 4) -> str:
    """One line per content word in the tail: 'goat: coat, boat, vote, note, wrote'.
    Empty when the tail reads as a trail-off rather than a finished phrase."""
    if not looks_like_swap(tail):
        return ""
    words = [w for w in _WORD.findall(tail.lower()) if w not in STOP and len(w) >= 3]
    seen: list[str] = []
    for w in reversed(words):           # the stall is usually at the end
        if w not in seen:
            seen.append(w)
        if len(seen) == max_words:
            break
    lines = []
    for w in seen:
        alikes = sound_alikes(w, per_word)
        if alikes:
            lines.append(f"{w}: " + ", ".join(alikes))
    return "\n".join(lines)
