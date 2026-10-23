"""Replay a synthetic match through the stats engine and the agent crew, printing overlays.

    python -m agents --seed 7 --speed 30          # uses Foundry if AZURE_AI_PROJECT_ENDPOINT is set
    python -m agents --seed 7 --offline --speed 0 # no Azure, instant
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from simulator import MatchSimulator, northgate_united, riverside_athletic
from stats_engine import MatchState

from .config import Settings
from .crew import Crew


async def run(args) -> None:
    if args.offline:
        os.environ["GALLERY_MODE"] = "offline"
    settings = Settings.from_env()
    if args.languages:
        settings.languages = args.languages.split(",")
    state = MatchState()
    match = MatchSimulator(riverside_athletic(), northgate_united(), seed=args.seed).run()

    def show(ov):
        flag = "✓" if ov.verified else "~"
        agents = " → ".join(ov.produced_by)
        print(f"\n{ov.minute:>3}' [{ov.kind.value}] {flag} {ov.headline}")
        if ov.kind.value not in ("player_tag", "shot_speed", "pass_quality", "milestone"):
            print(f"      {ov.body}")
            for lang, v in ov.variants.items():
                if lang != "en":
                    print(f"      ({lang}) {v['casual'].headline}: {v['casual'].body[:110]}")
            print(f"      agents: {agents}")

    crew = Crew(settings, state, on_overlay=show)
    print(f"mode={settings.mode} model={settings.fast_model} languages={settings.languages}")
    if settings.mode == "offline" and not args.offline:
        print("WARNING: no AZURE_AI_PROJECT_ENDPOINT found (.env in this folder or a parent), "
              "so the scripted offline client is being used instead of Foundry.")
    started = time.monotonic()
    for env in match.envelopes():
        t = env.event.second if env.event else env.frame.second if env.frame else 0.0
        if args.until and t > args.until * 60:
            break
        if args.speed > 0:
            wait = t / args.speed - (time.monotonic() - started)
            if wait > 0:
                await asyncio.sleep(wait)
        crew.submit(state.ingest(env))
        if env.kind == "frame":
            crew.tick(env.frame.second)
            await asyncio.sleep(0)
    await crew.drain()
    if crew.board.recap and not args.until:
        r = crew.board.recap["recap"]
        print("\n==== RECAP ====\n" + r["headline"])
        for p in r["paragraphs"]:
            print(" ", p)
    print("\nstats:", json.dumps(crew.board.stats))


def main() -> None:
    ap = argparse.ArgumentParser(prog="agents")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--speed", type=float, default=0, help="match-seconds per real second (0 = as fast as possible)")
    ap.add_argument("--until", type=int, default=0, help="stop at this minute")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--languages", default="")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
