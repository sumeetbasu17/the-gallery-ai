"""Evaluate The Gallery against synthetic ground truth.

    python scripts/evaluate.py --matches 20                 # detectors only (fast, no models)
    python scripts/evaluate.py --matches 3 --crew           # + agent crew on your Foundry models
    python scripts/evaluate.py --matches 3 --crew --offline # + crew with the scripted client

Measures
  Detection   recall / precision of block and width shifts vs the planted tactical timeline
              (random scenarios, so the detectors are tested on situations they were not tuned on)
  Grounding   share of aired stories approved by the Fact-Checker on the first draft, rejections,
              template fallbacks, and the share of overlays that are fact-checked
  Latency     p50 / p95 per agent
Writes docs/evaluation.md.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "packages" / "schema"), str(ROOT / "services")]

from simulator import MatchSimulator  # noqa: E402
from simulator.scenarios import ground_truth, random_scenario, teams_from_scenario  # noqa: E402
from stats_engine import MatchState, SignalType  # noqa: E402

WINDOW_MIN = 8
BLOCK_LEVEL = {"high": 2, "mid": 1, "low": 0}


def expected_changes(home, away) -> list[dict]:
    """Ground-truth changes big enough that a viewer would notice them."""
    out = []
    for g in ground_truth(home, away):
        block_moves = BLOCK_LEVEL[g["block"][0]] != BLOCK_LEVEL[g["block"][1]]
        width_moves = g["width"][0] != g["width"][1] and "balanced" not in g["width"] or (
            {"wide", "narrow"} == set(g["width"]))
        if block_moves:
            out.append({**g, "kind": "block"})
        if width_moves:
            out.append({**g, "kind": "width"})
    return out


async def run_match(seed: int, crew_on: bool, settings=None):
    scenario = random_scenario(seed) if seed >= 100 else None
    if scenario:
        home, away = teams_from_scenario(scenario)
    else:
        from simulator import northgate_united, riverside_athletic

        home, away = riverside_athletic(), northgate_united()
    match = MatchSimulator(home, away, seed=seed).run()
    state, signals = MatchState(), []
    crew = None
    if crew_on:
        from agents import Crew

        crew = Crew(settings, state)
    for env in match.envelopes():
        new = state.ingest(env)
        signals += new
        if crew:
            crew.submit(new)
            if env.kind == "frame":
                crew.tick(env.frame.second)
                await asyncio.sleep(0)
    if crew:
        await crew.drain()
    return home, away, signals, crew


def score_detection(home, away, signals):
    exp = expected_changes(home, away)
    got = [s for s in signals if s.type in (SignalType.BLOCK_SHIFT, SignalType.WIDTH_SHIFT)]
    hit_exp, used = 0, set()
    for e in exp:
        kind = SignalType.BLOCK_SHIFT if e["kind"] == "block" else SignalType.WIDTH_SHIFT
        for i, s in enumerate(got):
            if i not in used and s.type == kind and s.side == e["side"] and \
                    e["minute"] <= s.minute <= e["minute"] + WINDOW_MIN:
                hit_exp += 1
                used.add(i)
                break
    true_pos = 0
    for s in got:
        if any(s.side == e["side"] and e["minute"] - 1 <= s.minute <= e["minute"] + WINDOW_MIN
               for e in ground_truth(home, away)):
            true_pos += 1
    return len(exp), hit_exp, len(got), true_pos


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


async def main_async(args):
    settings = None
    if args.crew:
        if args.offline:
            os.environ["GALLERY_MODE"] = "offline"
        from agents import Settings

        settings = Settings.from_env()
        settings.languages = args.languages.split(",")

    seeds = [7] + [100 + i for i in range(args.matches - 1)]
    totals = defaultdict(int)
    latencies = defaultdict(list)
    t0 = time.time()
    for seed in seeds:
        home, away, signals, crew = await run_match(seed, args.crew, settings)
        n_exp, hits, n_got, tp = score_detection(home, away, signals)
        totals["expected"] += n_exp
        totals["hits"] += hits
        totals["detected"] += n_got
        totals["true_pos"] += tp
        if crew:
            narrative = [o for o in crew.board.overlays if o.kind.value in ("tactical_shift", "key_moment",
                                                                              "match_status")]
            totals["narrative"] += len(narrative)
            totals["verified"] += sum(o.verified for o in narrative)
            for o in narrative:
                rejected = any(s.agent == "fact_checker" and "verify numbers" in s.action and s.status == "rejected"
                               for s in o.trace)
                if o.verified and not rejected:
                    totals["first_pass"] += 1
                for s in o.trace:
                    if s.ms:
                        latencies[s.agent].append(s.ms)
            totals["rejections"] += crew.board.stats["rejections"]
            totals["fallbacks"] += crew.board.stats["fallbacks"]
            totals["errors"] += crew.board.stats["errors"]
            totals["llm_calls"] += crew.board.stats["llm_calls"]
        print(f"seed {seed}: expected {n_exp}, detected {hits}/{n_exp}, signals {n_got} (true {tp})", flush=True)

    lines = ["# Evaluation", "",
             f"Run: {len(seeds)} matches ({'with' if args.crew else 'without'} the agent crew"
             f"{', offline client' if args.offline else ''}), {time.time() - t0:.0f} s.", "",
             "Match 1 uses the default storyline; the rest use **random tactical scenarios** the detectors were "
             "not tuned on.", "", "## Tactical detection vs planted ground truth", "",
             "| Metric | Value |", "|---|---|",
             f"| Planted block/width changes | {totals['expected']} |",
             f"| Recall (found within {WINDOW_MIN} min) | {pct(totals['hits'], totals['expected'])} |",
             f"| Shape signals raised | {totals['detected']} |",
             f"| Precision (signal near a real planted change) | {pct(totals['true_pos'], totals['detected'])} |"]
    if args.crew:
        lines += ["", "## Agent crew", "", "| Metric | Value |", "|---|---|",
                  f"| Narrative overlays aired | {totals['narrative']} |",
                  f"| Fact-checked (verified) | {pct(totals['verified'], totals['narrative'])} |",
                  f"| Approved on first draft | {pct(totals['first_pass'], totals['narrative'])} |",
                  f"| Fact-check rejections (sent back for rewrite) | {totals['rejections']} |",
                  f"| Template fallbacks | {totals['fallbacks']} |",
                  f"| Model/tool errors recovered | {totals['errors']} |",
                  f"| LLM calls per match | {totals['llm_calls'] / len(seeds):.0f} |",
                  "", "## Latency per agent (ms)", "", "| Agent | p50 | p95 | calls |", "|---|---|---|---|"]
        for agent, xs in sorted(latencies.items()):
            xs = sorted(xs)
            p95 = xs[min(len(xs) - 1, int(0.95 * len(xs)))]
            lines.append(f"| {agent} | {statistics.median(xs):.0f} | {p95:.0f} | {len(xs)} |")
    out = ROOT / "docs" / "evaluation.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten to {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=10)
    ap.add_argument("--crew", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--languages", default="en,hi,es")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
