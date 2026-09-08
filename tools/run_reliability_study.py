"""Execute RELIABILITY-STUDY-v0.1 under the frozen frame. NOT A GAME.

Runs 4 arms x 2 trials over the frozen corpus in the frozen Stage 1 order:

* **fresh**: independent conversation, `store=false`, no `previous_response_id`;
* **chain**: branched from that position's own stored response, `store=false`.

Arms are labelled by what they actually are, not by a tidy 2x2:

* chain arm whose protocol matches the source game -> `native-chain`
* chain arm whose protocol differs -> `switched-current-turn`

Stage 1 is the first 20 positions, 160 responses. If it produces 0 to 2 illegal
responses in total the study stops there and reports no comparative conclusion.
Three or more continues to all 40 positions. A $40 study guard is checked before
every request. Responses are written as they happen, so nothing is lost if the
run is interrupted.

    python3 tools/run_reliability_study.py --stage 1
    python3 tools/run_reliability_study.py --stage 2
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from failure_probe import judge, state_at_ply  # noqa: E402

from bzbench.adapters.openai_api import OpenAIResponsesAdapter  # noqa: E402
from bzbench.config import Protocol  # noqa: E402
from bzbench.pricing import Pricing  # noqa: E402
from bzbench.protocol import build_prompt  # noqa: E402
from bzbench.record import GameRecord  # noqa: E402

STUDY_DIR = REPO / "results/diagnostics/reliability-study-v0.1"
GUARD_USD = 40.0
TRIALS = 2
FUTILITY_MAX_FAILURES = 2


class StudyGuard(RuntimeError):
    pass


def arm_label(arm_protocol: str, context: str, source_protocol: str) -> str:
    if context == "fresh":
        return f"fresh-{arm_protocol}"
    return ("native-chain" if arm_protocol == source_protocol
            else "switched-current-turn") + f"-{arm_protocol}"


def load_positions(stage: int) -> list[dict]:
    corpus = json.loads((STUDY_DIR / "corpus.json").read_text())
    order = json.loads((STUDY_DIR / "stage1-order.json").read_text())
    index = {f"{p['game_id']}#{p['depth']}": p for p in corpus["positions"]}
    keys = order["stage1"] if stage == 1 else order["stage2"]
    return [index[k] for k in keys]


def spent_so_far() -> float:
    total = 0.0
    for path in STUDY_DIR.glob("responses-stage*.jsonl"):
        for line in path.read_text().splitlines():
            if line.strip():
                total += float(json.loads(line)["cost"].get("total_cost_usd") or 0)
    return total


def run(args: argparse.Namespace) -> int:
    positions = load_positions(args.stage)
    pricing = Pricing.for_model(args.api_model)
    out = STUDY_DIR / f"responses-stage{args.stage}.jsonl"
    if out.exists() and not args.append:
        print(f"{out} exists; pass --append to continue an interrupted run",
              file=sys.stderr)
        return 2

    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((row["position"], row["arm"], row["trial"]))

    spent = spent_so_far()
    records: dict[str, GameRecord] = {}
    failures = 0
    started = time.monotonic()
    print(f"RELIABILITY-STUDY-v0.1 stage {args.stage}: {len(positions)} positions, "
          f"{len(positions) * 4 * TRIALS} responses, guard ${GUARD_USD:.2f}, "
          f"already spent ${spent:.4f}\n")

    for index, position in enumerate(positions, 1):
        path = REPO / position["source_path"]
        record = records.setdefault(str(path), GameRecord.load(path))
        board, history, colour = state_at_ply(record, position["ply"])
        # Self check: the corpus, the record and the replay must agree.
        assert board.fen() == position["fen"], position
        api = next(t.api for t in record.turns
                   if t.ply == position["ply"] and t.actor == "ai")
        assert api["response_id"] == position["response_id"], position

        key = f"{position['game_id']}#{position['depth']}"
        line = (f"[{index}/{len(positions)}] {key} depth {position['depth']} "
                f"{position['depth_bin']} {position['source_protocol']}-source")
        print(line)
        for context in ("fresh", "chain"):
            for arm_protocol in ("raw", "fen"):
                prompt, view = build_prompt(
                    board, history, Protocol(arm_protocol), colour
                )
                label = arm_label(arm_protocol, context, position["source_protocol"])
                for trial in range(1, TRIALS + 1):
                    if (key, label, trial) in done:
                        continue
                    if spent >= GUARD_USD:
                        raise StudyGuard(
                            f"study guard ${GUARD_USD:.2f} reached at ${spent:.4f}"
                        )
                    adapter = OpenAIResponsesAdapter(
                        model=args.api_model,
                        reasoning_effort=args.reasoning_effort,
                        pricing=pricing,
                        max_output_tokens=args.max_output_tokens,
                        max_cost_usd=GUARD_USD,
                        store=False,
                        resume_response_id=(
                            position["response_id"] if context == "chain" else None
                        ),
                        game_id=f"study-{key}-{label}-{trial}",
                    )
                    raw = adapter.propose_move(prompt, view)
                    meta = adapter.pop_turn_metadata() or {}
                    verdict = judge(board, raw)
                    cost = meta.get("cost", {})
                    spent += float(cost.get("total_cost_usd") or 0)
                    if not verdict["legal"]:
                        failures += 1
                    row = {
                        "study": "RELIABILITY-STUDY-v0.1",
                        "stage": args.stage,
                        "position": key,
                        "game_id": position["game_id"],
                        "source_protocol": position["source_protocol"],
                        "ply": position["ply"],
                        "depth": position["depth"],
                        "depth_bin": position["depth_bin"],
                        "side_to_move": position["side_to_move"],
                        "context": context,
                        "arm_protocol": arm_protocol,
                        "arm": label,
                        "trial": trial,
                        "raw_response": raw,
                        **{k: verdict[k] for k in
                           ("normalized", "legal", "reason", "category", "uci")},
                        "usage": meta.get("usage"),
                        "cost": cost,
                        "response_id": meta.get("response_id"),
                        "previous_response_id": meta.get("previous_response_id"),
                        "status": meta.get("status"),
                        "at": dt.datetime.now(dt.timezone.utc).isoformat(
                            timespec="seconds"),
                    }
                    with out.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(row) + "\n")
                    mark = "ok" if verdict["legal"] else verdict["category"].upper()
                    print(f"    {label:28} t{trial} {raw.strip()[:12]!r:16} {mark}"
                          f"  ${spent:.3f}")

    elapsed = (time.monotonic() - started) / 60
    print(f"\nstage {args.stage} complete: {failures} illegal responses, "
          f"${spent:.4f} spent, {elapsed:.1f} min")
    if args.stage == 1:
        if failures <= FUTILITY_MAX_FAILURES:
            print(f"FUTILITY STOP: {failures} illegal responses is at or below "
                  f"{FUTILITY_MAX_FAILURES}. Report the arm counts and make no "
                  f"comparative conclusion. Do not run stage 2.")
        else:
            print(f"CONTINUE: {failures} illegal responses exceeds "
                  f"{FUTILITY_MAX_FAILURES}. Stage 2 is authorised by the frozen "
                  f"rule.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", type=int, choices=(1, 2), required=True)
    parser.add_argument("--api-model", default="gpt-6-astra")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    parser.add_argument("--append", action="store_true",
                        help="continue an interrupted run, skipping completed cells")
    return parser


if __name__ == "__main__":
    try:
        raise SystemExit(run(build_parser().parse_args()))
    except StudyGuard as exc:
        print(f"\nSTOPPED: {exc}", file=sys.stderr)
        raise SystemExit(3)
