"""Generate a labelled synthetic dataset of many matches.

    python -m simulator.dataset --matches 50 --out data/generated/dataset --frames

Writes, per match: events.jsonl (and frames.jsonl with --frames), plus
  matches.csv   one row per match: score, shots, xG, passes, completion
  labels.jsonl  ground-truth tactical changes for every match

The files load directly into a Microsoft Fabric Lakehouse or Eventhouse (or any
dataframe) for analytics and for training or evaluating detectors.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .engine import MatchSimulator
from .scenarios import ground_truth, random_scenario, teams_from_scenario


def generate(n: int, out: Path, frames: bool, start_seed: int = 1000) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (out / "labels.jsonl").open("w", encoding="utf-8") as labels_fh:
        for i in range(n):
            seed = start_seed + i
            scenario = random_scenario(seed)
            home, away = teams_from_scenario(scenario)
            match = MatchSimulator(home, away, seed=seed, match_id=f"S{seed:05d}").run(with_frames=frames)
            mdir = out / match.metadata.match_id
            mdir.mkdir(exist_ok=True)
            with (mdir / "events.jsonl").open("w", encoding="utf-8") as fh:
                for e in match.events:
                    fh.write(e.model_dump_json(exclude_none=True) + "\n")
            if frames:
                with (mdir / "frames.jsonl").open("w", encoding="utf-8") as fh:
                    for f in match.frames:
                        fh.write(f.model_dump_json() + "\n")
            (mdir / "metadata.json").write_text(match.metadata.model_dump_json(indent=1), encoding="utf-8")
            labels_fh.write(json.dumps({"match_id": match.metadata.match_id, "scenario": scenario,
                                        "changes": ground_truth(home, away)}) + "\n")
            ev = match.events
            row = {"match_id": match.metadata.match_id, "seed": seed}
            for side in ("home", "away"):
                passes = [e for e in ev if e.type.value == "pass" and e.side and e.side.value == side]
                shots = [e for e in ev if e.type.value == "shot" and e.side and e.side.value == side]
                row.update({
                    f"{side}_goals": sum(1 for e in ev if e.type.value == "goal" and e.side and e.side.value == side),
                    f"{side}_shots": len(shots),
                    f"{side}_xg": round(sum(e.xg or 0 for e in shots), 2),
                    f"{side}_passes": len(passes),
                    f"{side}_completion": round(sum(e.outcome == "success" for e in passes) / max(len(passes), 1), 3),
                })
            rows.append(row)
    with (out / "matches.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"matches": n, "out": str(out)}


def main() -> None:
    ap = argparse.ArgumentParser(prog="simulator.dataset")
    ap.add_argument("--matches", type=int, default=20)
    ap.add_argument("--out", default="data/generated/dataset")
    ap.add_argument("--frames", action="store_true")
    ap.add_argument("--start-seed", type=int, default=1000)
    args = ap.parse_args()
    print(generate(args.matches, Path(args.out), args.frames, args.start_seed))


if __name__ == "__main__":
    main()
