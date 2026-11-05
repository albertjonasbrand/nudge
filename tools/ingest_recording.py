"""Turn a recording of Dad into stall test cases.

    python tools/ingest_recording.py call1.m4a --dad "first speaker"
    python tools/ingest_recording.py call1.m4a --diarize          # needs HF_TOKEN for pyannote
    python tools/ingest_recording.py call1.m4a --single           # only Dad on the track (Zoom per-participant)

Writes tests/stalls/review/<name>.yaml with one entry per suspected stall:
the minute of context before it, the tail, and an empty `target:` for you to
fill in. Then:

    python tools/ingest_recording.py --merge tests/stalls/review/call1.yaml

copies the filled-in ones into tests/stalls/real.yaml, which the harness runs
with --set real. Audio never leaves the machine; only text goes in the repo.

Stall detection is deliberately loose (better to review 40 and keep 15):
  - a filler run ("uh", "um", "the, the", "you know") near the end of a segment
  - a pause > 1.2 s inside his turn
  - a trailing article/preposition ("...went to the")
  - a repeated word within 3 words
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REVIEW_DIR = ROOT / "tests" / "stalls" / "review"
REAL = ROOT / "tests" / "stalls" / "real.yaml"

FILLERS = {"uh", "um", "er", "hmm", "mm", "ah"}
TRAIL = {"the", "a", "an", "my", "your", "to", "of", "for", "at", "in", "on", "with", "and", "that"}
PAUSE_S = 1.2
CONTEXT_S = 60.0
TAIL_S = 6.0


def transcribe(path: Path, model_size: str = "medium.en"):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments, _ = model.transcribe(str(path), word_timestamps=True, language="en",
                                   vad_filter=True, condition_on_previous_text=False)
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "s": float(w.start), "e": float(w.end), "spk": None})
    return words


def diarize(path: Path, words: list[dict]) -> None:
    import os
    from pyannote.audio import Pipeline
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("set HF_TOKEN (and accept the pyannote model terms on Hugging Face) to diarize")
    pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
    dia = pipe(str(path), num_speakers=2)
    turns = [(t.start, t.end, spk) for t, _, spk in dia.itertracks(yield_label=True)]
    for w in words:
        mid = (w["s"] + w["e"]) / 2
        w["spk"] = next((spk for s, e, spk in turns if s <= mid <= e), None)


def pick_dad(words: list[dict], hint: str) -> str | None:
    spks = [w["spk"] for w in words if w["spk"]]
    if not spks:
        return None
    order = []
    for s in spks:
        if s not in order:
            order.append(s)
    if hint.startswith("first"):
        return order[0]
    if hint.startswith("second") and len(order) > 1:
        return order[1]
    if hint.startswith("most"):
        return max(order, key=spks.count)
    return hint if hint in order else order[0]


def find_stalls(words: list[dict], dad: str | None) -> list[dict]:
    mine = [w for w in words if dad is None or w["spk"] == dad]
    out = []
    for i, w in enumerate(mine):
        tok = re.sub(r"[^a-z']", "", w["w"].lower())
        reasons = []
        if tok in FILLERS:
            reasons.append("filler")
        if i >= 1 and tok and tok == re.sub(r"[^a-z']", "", mine[i - 1]["w"].lower()):
            reasons.append("repeat")
        if i + 1 < len(mine) and mine[i + 1]["s"] - w["e"] > PAUSE_S:
            reasons.append(f"pause {mine[i+1]['s'] - w['e']:.1f}s")
        if tok in TRAIL and (i + 1 == len(mine) or mine[i + 1]["s"] - w["e"] > 0.6):
            reasons.append("trailing")
        if reasons:
            out.append({"t": round(w["e"], 1), "why": ", ".join(reasons)})
    # collapse hits within 4 s of each other into one stall at the latest point
    merged: list[dict] = []
    for h in out:
        if merged and h["t"] - merged[-1]["t"] < 4.0:
            merged[-1]["t"] = h["t"]
            merged[-1]["why"] += "; " + h["why"]
        else:
            merged.append(h)
    return merged


def text_between(words: list[dict], t0: float, t1: float, dad: str | None, label: bool) -> str:
    parts = []
    cur = None
    for w in words:
        if t0 <= w["e"] <= t1:
            if label and w["spk"] and w["spk"] != cur:
                cur = w["spk"]
                parts.append(f"\n{'DAD' if cur == dad else 'OTHER'}:")
            parts.append(w["w"])
    return " ".join(parts).strip()


def fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="?")
    ap.add_argument("--dad", default="most", help='"first", "second", "most" (talks most), or a speaker label')
    ap.add_argument("--diarize", action="store_true", help="split speakers with pyannote (needs HF_TOKEN)")
    ap.add_argument("--single", action="store_true", help="the track is only Dad")
    ap.add_argument("--whisper", default="medium.en")
    ap.add_argument("--merge", help="review YAML to merge into tests/stalls/real.yaml")
    args = ap.parse_args()

    if args.merge:
        return merge(Path(args.merge))
    if not args.audio:
        ap.error("audio file required")

    path = Path(args.audio)
    print(f"transcribing {path.name} with {args.whisper} ...")
    words = transcribe(path, args.whisper)
    print(f"  {len(words)} words, {fmt(words[-1]['e']) if words else '0:00'} long")

    dad = None
    if args.diarize and not args.single:
        print("diarizing ...")
        diarize(path, words)
        dad = pick_dad(words, args.dad)
        n = sum(1 for w in words if w["spk"] == dad)
        print(f"  Dad = {dad} ({n} words)")

    stalls = find_stalls(words, dad)
    print(f"  {len(stalls)} suspected stalls")

    entries = []
    for k, st in enumerate(stalls, 1):
        t = st["t"]
        entries.append({
            "id": f"{path.stem}-{k:02d}",
            "at": fmt(t),
            "why": st["why"],
            "context": text_between(words, t - CONTEXT_S, t, dad, label=dad is not None),
            "tail": text_between([w for w in words if dad is None or w["spk"] == dad], t - TAIL_S, t, dad, False),
            "target": "",
            "accept": [],
            "type": "",
            "keep": True,
        })

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEW_DIR / f"{path.stem}.yaml"
    header = ("# Review: for each stall, fill `target` with the word he wanted (listen at `at`).\n"
              "# Set `keep: false` for false alarms. `type`: anomic | sound | semantic | circumlocution | lexicon\n"
              "# Then: python tools/ingest_recording.py --merge " + str(out.relative_to(ROOT)) + "\n\n")
    out.write_text(header + yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=100))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


def merge(review: Path) -> int:
    entries = yaml.safe_load(review.read_text()) or []
    keep = [e for e in entries if e.get("keep", True) and e.get("target")]
    existing = yaml.safe_load(REAL.read_text()) if REAL.exists() else []
    ids = {e["id"] for e in existing}
    added = 0
    for e in keep:
        if e["id"] in ids:
            continue
        existing.append({"id": e["id"], "type": e.get("type") or "anomic",
                         "context": e["context"].replace("\n", " ").strip(),
                         "tail": e["tail"].strip(), "target": e["target"],
                         "accept": e.get("accept") or [e["target"]]})
        added += 1
    REAL.write_text(yaml.safe_dump(existing, sort_keys=False, allow_unicode=True, width=100))
    print(f"merged {added} new stalls into {REAL.relative_to(ROOT)} ({len(existing)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
