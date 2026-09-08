"""Freeze the RELIABILITY-STUDY-v0.1 position corpus.

Samples 40 positions from the six completed games under the preregistered
frame, writes them once, and refuses to overwrite. The corpus records the six
source game ids with the sha256 of each published record, so it can be shown
later that the sample was drawn before any 1700 game existed.

Frame, all of it preregistered in docs/reliability-study-v0.1.md:

* per game quotas: 8 from each RAW game, 6 from each FEN game, 40 total;
* depth strata, counted as Astra turns already accumulated before the sampled
  turn: early 5 to 10, middle 11 to 20, late 21 or more, target 13/13/14;
* minimum separation of 3 accumulated turns within a game, relaxed to 2 then 1
  only where a game is too short for its quota, recorded per game;
* per game quotas win over the depth targets if both cannot be met, and any
  depth shortfall is recorded;
* selection uses no engine information. Sharpness and board features are
  recorded as covariates afterwards.

    python3 tools/build_corpus.py --out results/diagnostics/reliability-study-v0.1/corpus.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import random
import sys

import chess

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bzbench.record import GameRecord  # noqa: E402

SOURCES = [
    ("results/api-pilot-v0.1/game-001/game.json", "raw", 8),
    ("results/api-pilot-v0.1/game-002/game.json", "raw", 8),
    ("results/api-pilot-fen-v0.1/game-001/game.json", "fen", 6),
    ("results/api-pilot-fen-v0.1/game-002/game.json", "fen", 6),
    ("results/api-pilot-fen-v0.2/game-001/game.json", "fen", 6),
    ("results/api-pilot-fen-v0.2/game-002/game.json", "fen", 6),
]
DEPTH_TARGETS = {"early": 13, "middle": 13, "late": 14}
MIN_DEPTH = 5
SEPARATIONS = (3, 2, 1)


def depth_bin(depth: int) -> str:
    if depth <= 10:
        return "early"
    if depth <= 20:
        return "middle"
    return "late"


def candidates(record: GameRecord) -> list[dict]:
    """Every model turn deep enough to sample, with the state it needs."""
    board = chess.Board()
    history: list[str] = []
    seen = 0
    out: list[dict] = []
    for turn in record.turns:
        if turn.actor == "ai":
            api = turn.api or {}
            if seen >= MIN_DEPTH and api.get("response_id"):
                out.append(
                    {
                        "ply": turn.ply,
                        "depth": seen,
                        "depth_bin": depth_bin(seen),
                        "fen": board.fen(),
                        "side_to_move": "white" if board.turn else "black",
                        "response_id": api["response_id"],
                        "history_length": len(history),
                        "features": {
                            "in_check": board.is_check(),
                            "castling_rights": bool(board.castling_xfen() != "-"),
                            "promotion_available": any(
                                m.promotion for m in board.legal_moves
                            ),
                            "en_passant_available": board.has_legal_en_passant(),
                            "legal_moves": board.legal_moves.count(),
                        },
                    }
                )
            seen += 1
        if turn.uci:
            board.push(chess.Move.from_uci(turn.uci))
            history.append(turn.san or "")
    return out


def pick(pool: list[dict], quota: int, sep: int, weights: dict[str, float],
         rng: random.Random) -> list[dict] | None:
    """Greedy weighted pick honouring the separation, or None if it cannot fit."""
    for _ in range(400):
        chosen: list[dict] = []
        remaining = list(pool)
        while remaining and len(chosen) < quota:
            scores = [max(weights.get(c["depth_bin"], 0.0), 0.01) for c in remaining]
            candidate = rng.choices(remaining, weights=scores, k=1)[0]
            chosen.append(candidate)
            remaining = [
                c for c in remaining
                if all(abs(c["depth"] - x["depth"]) >= sep for x in chosen)
            ]
        if len(chosen) == quota:
            return sorted(chosen, key=lambda c: c["depth"])
    return None


def repair(positions: list[dict], games: list[dict], separations: dict[str, int],
           shortfall: int, rng: random.Random) -> tuple[int, list[dict]]:
    """Swap single positions within a game to close a depth bin shortfall.

    A swap keeps every per game quota and every separation intact; it only moves
    one position from an over filled depth bin to an under filled one inside the
    same game.
    """
    by_id = {g["game_id"]: g for g in games}
    for _ in range(2000):
        counts = {b: sum(1 for p in positions if p["depth_bin"] == b)
                  for b in DEPTH_TARGETS}
        over = [b for b, n in counts.items() if n > DEPTH_TARGETS[b]]
        under = [b for b, n in counts.items() if n < DEPTH_TARGETS[b]]
        if not over or not under:
            return sum(abs(counts[b] - DEPTH_TARGETS[b]) for b in DEPTH_TARGETS), positions
        target_out, target_in = rng.choice(over), rng.choice(under)
        movable = [p for p in positions if p["depth_bin"] == target_out]
        rng.shuffle(movable)
        for leaving in movable:
            game = by_id[leaving["game_id"]]
            sep = separations[game["game_id"]]
            kept = [p for p in positions if p is not leaving
                    and p["game_id"] == game["game_id"]]
            options = [
                c for c in game["candidates"]
                if c["depth_bin"] == target_in
                and all(abs(c["depth"] - k["depth"]) >= sep for k in kept)
            ]
            if not options:
                continue
            arriving = rng.choice(options)
            positions = [p for p in positions if p is not leaving] + [
                {**arriving, "game_id": game["game_id"],
                 "source_protocol": game["protocol"], "source_path": game["path"]}
            ]
            break
        else:
            continue
    counts = {b: sum(1 for p in positions if p["depth_bin"] == b) for b in DEPTH_TARGETS}
    return sum(abs(counts[b] - DEPTH_TARGETS[b]) for b in DEPTH_TARGETS), positions


def build(seed: int) -> dict:
    rng = random.Random(seed)
    games: list[dict] = []
    for path, protocol, quota in SOURCES:
        full = REPO / path
        record = GameRecord.load(full)
        games.append(
            {
                "path": path,
                "game_id": record.config.game_id,
                "protocol": protocol,
                "quota": quota,
                "record_sha256": hashlib.sha256(full.read_bytes()).hexdigest(),
                "benchmark_commit": record.environment.get("bzbench_commit"),
                "ai_color": record.config.ai_color.value,
                "stockfish_elo": record.effective_elo(),
                "candidates": candidates(record),
            }
        )

    best: tuple[int, list] | None = None
    for _ in range(600):
        need = dict(DEPTH_TARGETS)
        attempt: list[dict] = []
        separations: dict[str, int] = {}
        ok = True
        for game in sorted(games, key=lambda g: len(g["candidates"])):
            chosen = None
            for sep in SEPARATIONS:
                chosen = pick(game["candidates"], game["quota"], sep, need, rng)
                if chosen is not None:
                    separations[game["game_id"]] = sep
                    break
            if chosen is None:
                ok = False
                break
            for item in chosen:
                need[item["depth_bin"]] -= 1
                attempt.append({**item, "game_id": game["game_id"],
                                "source_protocol": game["protocol"],
                                "source_path": game["path"]})
        if not ok:
            continue
        shortfall = sum(abs(v) for v in need.values())
        if best is None or shortfall < best[0]:
            best = (shortfall, attempt, separations)
        if shortfall == 0:
            break

    if best is None:
        raise SystemExit("no feasible sample under the frozen frame")
    shortfall, positions, separations = best
    if shortfall:
        shortfall, positions = repair(positions, games, separations, shortfall, rng)
    counts = {b: sum(1 for p in positions if p["depth_bin"] == b)
              for b in DEPTH_TARGETS}
    return {
        "study": "RELIABILITY-STUDY-v0.1",
        "kind": "position_corpus",
        "scored": False,
        "frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "seed": seed,
        "frame": {
            "per_game_quotas": {g["game_id"]: g["quota"] for g in games},
            "depth_targets": DEPTH_TARGETS,
            "min_depth": MIN_DEPTH,
            "separation_preference": list(SEPARATIONS),
            "separation_used": separations,
            "selection_used_engine_information": False,
        },
        "sources": [
            {k: g[k] for k in ("game_id", "path", "protocol", "quota",
                               "record_sha256", "benchmark_commit", "ai_color",
                               "stockfish_elo")}
            for g in games
        ],
        "depth_counts": counts,
        "depth_shortfall": shortfall,
        "source_protocol_counts": {
            p: sum(1 for x in positions if x["source_protocol"] == p)
            for p in ("raw", "fen")
        },
        "side_to_move_counts": {
            c: sum(1 for x in positions if x["side_to_move"] == c)
            for c in ("white", "black")
        },
        "positions": sorted(
            positions, key=lambda p: (p["game_id"], p["depth"])
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    if out.exists() and not args.force:
        print(f"{out} already exists; a frozen corpus is never rewritten",
              file=sys.stderr)
        return 2
    corpus = build(args.seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(corpus, indent=2) + "\n"
    out.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (out.parent / "CORPUS.sha256").write_text(f"{digest}  {out.name}\n")

    print(f"frozen {len(corpus['positions'])} positions -> {out}")
    print(f"  sha256 {digest}")
    print(f"  depth counts {corpus['depth_counts']} (target {DEPTH_TARGETS}, "
          f"shortfall {corpus['depth_shortfall']})")
    print(f"  source protocol {corpus['source_protocol_counts']}")
    print(f"  side to move {corpus['side_to_move_counts']}")
    print(f"  separation used {corpus['frame']['separation_used']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
