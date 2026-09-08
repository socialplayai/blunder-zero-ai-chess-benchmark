"""Diagnostic probe of a single position. NOT A GAME, NOT ELO EVIDENCE.

Takes a closed game record and one ply from it, rebuilds the exact position and
the exact move history, and asks the model for one move from that state under
each protocol, several independent times.

It answers one causal question that waiting for another long game answers only
slowly:

    when the model is put back in the exact state that broke the RAW protocol,
    does authoritative position information prevent the impossible move?

Rules that keep this honest:

* the prompts come from the frozen `bzbench.protocol` builder, so a probe prompt
  is the same object a real game would have shown;
* the legality verdict comes from the frozen `parse_san_strict`, so a probe
  answer is judged exactly as a game answer would be;
* a fresh trial is an independent conversation: `store=false`, no
  `previous_response_id`, one adapter per trial, so trials cannot see each other
  and cannot touch any game;
* a chain trial branches from one stored response of a closed game, named by
  `--chain-from-ply`, with `store=false` so the branch is not itself stored.
  Branching reads a stored response, it does not modify it, and each trial
  branches independently from the same point, so no chain trial can see
  another;
* output is written outside `games/` and outside any scored path;
* nothing here produces a result, a win, a loss or an Elo estimate.

    python3 tools/failure_probe.py results/api-pilot-v0.1/game-002/game.json \
        --ply 45 --trials 5 --protocols raw fen --out diagnostics/<name>.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import chess

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bzbench.adapters.openai_api import OpenAIResponsesAdapter  # noqa: E402
from bzbench.config import Color, Protocol  # noqa: E402
from bzbench.pricing import Pricing, cost_of  # noqa: E402
from bzbench.protocol import PROMPT_VERSION, build_prompt  # noqa: E402
from bzbench.record import GameRecord, environment_fingerprint  # noqa: E402
from bzbench.referee import IllegalMove, parse_san_strict  # noqa: E402


class ProbeBudgetExceeded(RuntimeError):
    pass


def state_at_ply(record: GameRecord, ply: int) -> tuple[chess.Board, list[str], Color]:
    """Rebuild the board and the move history exactly as they were at `ply`."""
    board = chess.Board()
    history: list[str] = []
    for turn in record.turns:
        if turn.ply == ply:
            colour = Color.WHITE if board.turn == chess.WHITE else Color.BLACK
            return board, history, colour
        if turn.uci:
            board.push(chess.Move.from_uci(turn.uci))
            history.append(turn.san or "")
    raise SystemExit(f"ply {ply} not found in the record")


def response_id_at_ply(record: GameRecord, ply: int) -> str:
    """The provider response id of the model turn at `ply`, for branching."""
    for turn in record.turns:
        if turn.ply == ply and turn.actor == "ai":
            api = turn.api or {}
            response_id = api.get("response_id")
            if not response_id:
                raise SystemExit(f"no response id recorded at ply {ply}")
            return response_id
    raise SystemExit(f"no model turn at ply {ply}")


def judge(board: chess.Board, raw: str) -> dict:
    """Judge a response exactly as the referee would, without playing a game."""
    normalized = raw.strip()
    try:
        move = parse_san_strict(board, normalized)
    except IllegalMove as exc:
        reason = exc.reason
        return {
            "normalized": normalized,
            "legal": False,
            "reason": reason,
            "category": (
                "illegal_move_response"
                if reason
                in {
                    "move is not legal in this position",
                    "ambiguous SAN, matches more than one legal move",
                }
                else "malformed_response"
            ),
            "uci": None,
        }
    return {
        "normalized": normalized,
        "legal": True,
        "reason": None,
        "category": "legal",
        "uci": move.uci(),
    }


def run(args: argparse.Namespace) -> int:
    record = GameRecord.load(args.source)
    board, history, colour = state_at_ply(record, args.ply)
    pricing = Pricing.for_model(args.api_model)

    print(f"Diagnostic probe. NOT A GAME, NOT ELO EVIDENCE.\n")
    print(f"  source     {args.source}")
    print(f"  ply        {args.ply}  ({colour.value} to move)")
    print(f"  position   {board.fen()}")
    print(f"  legal      {len(list(board.legal_moves))} moves available")
    print(f"  trials     {args.trials} per protocol, protocols {args.protocols}")
    print(f"  guard      ${args.max_cost_usd:.2f} for the whole probe\n")

    chain_from: str | None = None
    if args.chain_from_ply is not None:
        chain_from = response_id_at_ply(record, args.chain_from_ply)
        print(f"  context    branching from the ply {args.chain_from_ply} response "
              f"{chain_from}\n")

    arm_prefix = "chain" if chain_from else "fresh"
    results: dict[str, list[dict]] = {}
    spent = 0.0
    for protocol_name in args.protocols:
        arm = f"{arm_prefix}-{protocol_name}"
        protocol = Protocol(protocol_name)
        prompt, view = build_prompt(board, history, protocol, colour)
        trials: list[dict] = []
        for trial in range(1, args.trials + 1):
            if spent >= args.max_cost_usd:
                raise ProbeBudgetExceeded(
                    f"probe guard of ${args.max_cost_usd:.2f} reached after "
                    f"${spent:.4f}"
                )
            adapter = OpenAIResponsesAdapter(
                model=args.api_model,
                reasoning_effort=args.reasoning_effort,
                pricing=pricing,
                max_output_tokens=args.max_output_tokens,
                max_cost_usd=args.max_cost_usd,
                store=False,          # the branch is not stored either
                resume_response_id=chain_from,
                game_id=f"probe-{arm}-{trial}",
            )
            raw = adapter.propose_move(prompt, view)
            meta = adapter.pop_turn_metadata() or {}
            verdict = judge(board, raw)
            cost = meta.get("cost", {})
            spent += float(cost.get("total_cost_usd") or 0.0)
            trials.append(
                {
                    "trial": trial,
                    "raw_response": raw,
                    **verdict,
                    "usage": meta.get("usage"),
                    "cost": cost,
                    "response_id": meta.get("response_id"),
                    "previous_response_id": meta.get("previous_response_id"),
                    "store": False,
                    "status": meta.get("status"),
                }
            )
            mark = "legal" if verdict["legal"] else verdict["category"]
            print(
                f"  [{arm}] trial {trial}: {raw.strip()!r} -> {mark}"
                f"  (${cost.get('total_cost_usd', 0):.4f})"
            )
        results[arm] = trials
        legal = sum(1 for t in trials if t["legal"])
        print(f"  [{arm}] {legal}/{len(trials)} legal\n")

    payload = {
        "kind": "diagnostic_probe",
        "scored": False,
        "note": (
            "Not a game. Not Elo evidence. Independent single position trials "
            "using the frozen prompt builder and the frozen SAN validator."
        ),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "environment": environment_fingerprint(),
        "source_record": str(args.source),
        "source_game_id": record.config.game_id,
        "ply": args.ply,
        "fen": board.fen(),
        "side_to_move": colour.value,
        "legal_moves": sorted(board.san(m) for m in board.legal_moves),
        "move_history": history,
        "prompt_version": PROMPT_VERSION,
        "model": args.api_model,
        "reasoning_effort": args.reasoning_effort,
        "max_output_tokens": args.max_output_tokens,
        "trials_per_protocol": args.trials,
        "context": "chain" if chain_from else "fresh",
        "chain_from_ply": args.chain_from_ply,
        "chain_from_response_id": chain_from,
        "prompts": {
            name: build_prompt(board, history, Protocol(name), colour)[0]
            for name in args.protocols
        },
        "results": results,
        "summary": {
            name: {
                "trials": len(trials),
                "legal": sum(1 for t in trials if t["legal"]),
                "illegal_move_responses": sum(
                    1 for t in trials if t["category"] == "illegal_move_response"
                ),
                "malformed": sum(
                    1 for t in trials if t["category"] == "malformed_response"
                ),
                "distinct_answers": sorted({t["normalized"] for t in trials}),
                "total_cost_usd": round(
                    sum(float(t["cost"].get("total_cost_usd") or 0) for t in trials), 6
                ),
                "total_output_tokens": sum(
                    int((t["usage"] or {}).get("output_tokens") or 0) for t in trials
                ),
                "total_reasoning_tokens": sum(
                    int((t["usage"] or {}).get("reasoning_tokens") or 0)
                    for t in trials
                ),
            }
            for name, trials in results.items()
        },
        "total_cost_usd": round(spent, 6),
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"  total probe cost ${spent:.4f}")
    print(f"  written to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("--ply", type=int, required=True,
                        help="the ply whose position and prompt are replayed")
    parser.add_argument("--chain-from-ply", type=int, default=None,
                        help="branch every trial from the stored response of the "
                             "model turn at this ply, reproducing the "
                             "conversational state the game was actually in")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--protocols", nargs="+", default=["raw", "fen"],
                        choices=["raw", "fen", "legal"])
    parser.add_argument("--api-model", default="gpt-6-astra")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    parser.add_argument("--max-cost-usd", type=float, default=5.0)
    parser.add_argument("--out", default="diagnostics/probe.json")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
