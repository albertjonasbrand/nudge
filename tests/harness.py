"""Score the resolver on the stall test set.

    python -m tests.harness --model models/qwen2.5-3b-instruct-q4_k_m.gguf
    python -m tests.harness --backend echo        # plumbing check, no model

Reports top-1 and top-3 hit rate overall and per stall type, plus latency.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

from nudge.lexicon import Lexicon
from nudge.resolver import Resolver

STALLS = Path(__file__).parent / "stalls" / "stalls.yaml"


class EchoBackend:
    """Returns the last word of the tail three times; proves the plumbing."""

    def complete(self, system: str, user: str) -> str:
        tail = user.split("BUTTON:")[-1].split("Three words")[0]
        words = [w.strip(",.") for w in tail.split() if w.strip(",.")]
        last = words[-1] if words else "um"
        return f"{last}\n{last}\n{last}"


def norm(w: str) -> str:
    return w.strip().lower().replace("-", " ")


def hit_rank(words: list[str], accept: list[str]) -> int | None:
    acc = {norm(a) for a in accept}
    for i, w in enumerate(words):
        if norm(w) in acc:
            return i + 1
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="path to a GGUF model")
    ap.add_argument("--backend", default="llama", choices=["llama", "echo"])
    ap.add_argument("--lexicon", default="config/lexicon.example.yaml")
    ap.add_argument("--n-gpu-layers", type=int, default=-1)
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--only", help="comma-separated stall ids or types to run")
    ap.add_argument("--no-hints", action="store_true", help="disable sound-alike hints")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--json", help="write per-stall results to this file")
    args = ap.parse_args()

    if args.backend == "echo":
        backend = EchoBackend()
    else:
        if not args.model:
            print("need --model for the llama backend", file=sys.stderr)
            return 2
        from nudge.resolver import LlamaBackend

        backend = LlamaBackend(args.model, n_gpu_layers=args.n_gpu_layers, n_threads=args.threads)

    lex = Lexicon(args.lexicon)
    resolver = Resolver(backend, lex, sound_hints=not args.no_hints)
    stalls = yaml.safe_load(STALLS.read_text())
    if args.only:
        keys = set(args.only.split(","))
        stalls = [s for s in stalls if s["id"] in keys or s["type"] in keys]

    # warm the prefix cache so the first timed call isn't paying for the system prompt
    resolver.resolve("hello", "hello")

    rows = []
    by_type: dict[str, list[int | None]] = defaultdict(list)
    for s in stalls:
        r = resolver.resolve(s["context"], s["tail"])
        rank = hit_rank(r.words, s.get("accept") or [s["target"]])
        by_type[s["type"]].append(rank)
        rows.append({"id": s["id"], "type": s["type"], "target": s["target"], "words": r.words,
                     "rank": rank, "ms": round(r.ms), "raw": r.raw})
        mark = {1: "✓", 2: "2", 3: "3"}.get(rank, "✗")
        if args.verbose or rank is None:
            print(f"{mark} {s['id']:4} {s['target']:<12} -> {r.words}  ({r.ms:.0f} ms)")

    def rate(ranks: list[int | None], k: int) -> float:
        return sum(1 for r in ranks if r is not None and r <= k) / max(1, len(ranks))

    all_ranks = [r for rs in by_type.values() for r in rs]
    lat = [row["ms"] for row in rows]
    print()
    print(f"{'type':<15}{'n':>4}{'top-1':>8}{'top-3':>8}")
    for t, rs in sorted(by_type.items()):
        print(f"{t:<15}{len(rs):>4}{rate(rs,1):>8.0%}{rate(rs,3):>8.0%}")
    print(f"{'ALL':<15}{len(all_ranks):>4}{rate(all_ranks,1):>8.0%}{rate(all_ranks,3):>8.0%}")
    print(f"\nlatency: median {statistics.median(lat):.0f} ms, p90 "
          f"{sorted(lat)[int(len(lat)*0.9)-1]:.0f} ms, max {max(lat):.0f} ms")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
