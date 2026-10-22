"""Run a synthetic match.

Examples
--------
Batch, write to a file:
    python -m simulator --seed 7 --out data/generated/match_7.jsonl

Live, printed to the terminal at 60x speed (90 minutes in 90 seconds):
    python -m simulator --seed 7 --live --speed 60

Live into Azure Event Hubs:
    python -m simulator --seed 7 --live --speed 10 --sink eventhub
"""

from __future__ import annotations

import argparse
import time

from .clubs import northgate_united, riverside_athletic
from .engine import MatchSimulator
from .sinks import ConsoleSink, EventHubSink, JsonlSink


def main() -> None:
    ap = argparse.ArgumentParser(prog="simulator")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=None, help="JSONL output path")
    ap.add_argument("--live", action="store_true", help="pace output to the match clock")
    ap.add_argument("--speed", type=float, default=1.0, help="clock multiplier in live mode")
    ap.add_argument("--sink", choices=["console", "jsonl", "eventhub"], default=None)
    ap.add_argument("--no-frames", action="store_true", help="skip tracking frames")
    args = ap.parse_args()

    home, away = riverside_athletic(), northgate_united()
    match = MatchSimulator(home, away, seed=args.seed).run(with_frames=not args.no_frames)
    names = {p.id: p.name for t in (home, away) for p in t.players}

    sink_kind = args.sink or ("jsonl" if args.out else "console")
    if sink_kind == "jsonl":
        sink = JsonlSink(args.out or f"data/generated/match_{args.seed}.jsonl")
    elif sink_kind == "eventhub":
        sink = EventHubSink()
    else:
        sink = ConsoleSink(names)

    started = time.monotonic()
    try:
        for env in match.envelopes():
            if args.live:
                t = env.event.second if env.event else env.frame.second if env.frame else 0.0
                wait = t / args.speed - (time.monotonic() - started)
                if wait > 0:
                    time.sleep(wait)
            sink.send(env)
    finally:
        sink.close()

    h, a = match.metadata.home, match.metadata.away
    final = next(e for e in reversed(match.events) if e.type.value == "full_time").detail["score"]
    print(f"Final: {h.name} {final['home']} - {final['away']} {a.name} "
          f"| {len(match.events)} events, {len(match.frames)} frames")


if __name__ == "__main__":
    main()
