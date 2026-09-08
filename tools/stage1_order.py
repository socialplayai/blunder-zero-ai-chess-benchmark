"""Define the RELIABILITY-STUDY-v0.1 execution order. Amendment C1.

The frozen corpus defines the **sample**, not an execution order: positions are
stored sorted by (game_id, depth) for readability, so a naive "first 20" would
be 20 FEN source positions from four of the six games. The Stage 1 futility stop
consumes the first 20 positions, so an undefined order would let the stop depend
on an arbitrary alphabetical artefact.

This tool defines that order once, deterministically, before any study response
exists. It **does not touch the corpus**: no position is added, removed or
substituted, and no engine information is used. It only decides which 20 of the
already frozen 40 constitute Stage 1, and in what order all 40 are executed.

Stage 1 targets, from the ruling:

* 8 RAW source and 12 FEN source;
* all six games represented, 4 from each RAW game and 3 from each FEN game;
* 10 positions with White to move and 10 with Black, which follows from the
  per game quotas because each game has one Astra colour;
* each depth stratum represented roughly equally, 7 early, 6 middle, 7 late.

    python3 tools/stage1_order.py --corpus <corpus.json> --out <stage1.json>
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import random
import sys

STAGE1_QUOTAS = {"raw": 4, "fen": 3}      # per game, by source protocol
STAGE1_DEPTH_TARGETS = {"early": 7, "middle": 6, "late": 7}


def key(position: dict) -> str:
    return f"{position['game_id']}#{position['depth']}"


def choose_stage1(positions: list[dict], rng: random.Random) -> list[dict]:
    """Pick the Stage 1 half: per game quotas exactly, depth strata as close as
    the per game quotas allow."""
    by_game: dict[str, list[dict]] = {}
    for position in positions:
        by_game.setdefault(position["game_id"], []).append(position)

    best: tuple[int, list[dict]] | None = None
    for _ in range(4000):
        picked: list[dict] = []
        need = dict(STAGE1_DEPTH_TARGETS)
        for game_id in sorted(by_game):
            pool = by_game[game_id]
            quota = STAGE1_QUOTAS[pool[0]["source_protocol"]]
            weights = [max(need.get(p["depth_bin"], 0), 0) + 0.25 for p in pool]
            chosen: list[dict] = []
            remaining = list(pool)
            remaining_w = list(weights)
            while remaining and len(chosen) < quota:
                item = rng.choices(remaining, weights=remaining_w, k=1)[0]
                index = remaining.index(item)
                remaining.pop(index)
                remaining_w.pop(index)
                chosen.append(item)
                need[item["depth_bin"]] -= 1
            picked.extend(chosen)
        counts = {b: sum(1 for p in picked if p["depth_bin"] == b)
                  for b in STAGE1_DEPTH_TARGETS}
        gap = sum(abs(counts[b] - STAGE1_DEPTH_TARGETS[b])
                  for b in STAGE1_DEPTH_TARGETS)
        if best is None or gap < best[0]:
            best = (gap, picked)
        if gap == 0:
            break
    assert best is not None
    return best[1]


def build(corpus: dict, seed: int) -> dict:
    rng = random.Random(seed)
    positions = corpus["positions"]
    stage1 = choose_stage1(positions, rng)
    stage1_keys = {key(p) for p in stage1}
    stage2 = [p for p in positions if key(p) not in stage1_keys]

    order1 = sorted(stage1, key=key)
    order2 = sorted(stage2, key=key)
    rng.shuffle(order1)
    rng.shuffle(order2)

    def summarise(items: list[dict]) -> dict:
        return {
            "n": len(items),
            "source_protocol": {
                p: sum(1 for x in items if x["source_protocol"] == p)
                for p in ("raw", "fen")
            },
            "per_game": {
                g: sum(1 for x in items if x["game_id"] == g)
                for g in sorted({x["game_id"] for x in positions})
            },
            "side_to_move": {
                c: sum(1 for x in items if x["side_to_move"] == c)
                for c in ("white", "black")
            },
            "depth_bins": {
                b: sum(1 for x in items if x["depth_bin"] == b)
                for b in STAGE1_DEPTH_TARGETS
            },
        }

    return {
        "study": "RELIABILITY-STUDY-v0.1",
        "amendment": "C1, execution order",
        "kind": "execution_order",
        "scored": False,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "seed": seed,
        "corpus_sha256": hashlib.sha256(
            (json.dumps(corpus, indent=2) + "\n").encode()
        ).hexdigest(),
        "note": (
            "Defines which 20 of the frozen 40 form Stage 1 and the order all 40 "
            "run in. The corpus is unchanged: no position added, removed or "
            "substituted, and no engine information used."
        ),
        "stage1_targets": {
            "per_game_quotas": STAGE1_QUOTAS,
            "depth": STAGE1_DEPTH_TARGETS,
            "source_protocol": {"raw": 8, "fen": 12},
            "side_to_move": {"white": 10, "black": 10},
        },
        "stage1_achieved": summarise(order1),
        "stage2_achieved": summarise(order2),
        "stage1": [key(p) for p in order1],
        "stage2": [key(p) for p in order2],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    if out.exists() and not args.force:
        print(f"{out} already exists; the execution order is frozen once",
              file=sys.stderr)
        return 2
    corpus = json.loads(pathlib.Path(args.corpus).read_text())
    order = build(corpus, args.seed)
    out.write_text(json.dumps(order, indent=2) + "\n", encoding="utf-8")
    print(f"stage 1 = {len(order['stage1'])} positions, "
          f"stage 2 = {len(order['stage2'])}")
    for name in ("source_protocol", "per_game", "side_to_move", "depth_bins"):
        print(f"  stage1 {name}: {order['stage1_achieved'][name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
