"""Command line interface.

    bzbench play      run one benchmark game
    bzbench analyze   post-game Stockfish analysis of a saved game
    bzbench summarize summary statistics over saved games
    bzbench show      audit what a game showed the AI player
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from typing import Any

from . import adapters
from .analysis import analyse_record
from .config import Color, MatchConfig, Protocol
from .engine import EngineUnavailable, StockfishOpponent
from .record import Actor, GameRecord
from .referee import Referee
from .stats import aggregate, format_table, game_summary, load_records

DEFAULT_GAMES_DIR = "games"


# --------------------------------------------------------------------------
# play
# --------------------------------------------------------------------------


def _config_from_args(args: argparse.Namespace) -> MatchConfig:
    kwargs: dict[str, Any] = {
        "model_name": args.model,
        "protocol": Protocol(args.protocol),
        "ai_color": Color(args.color),
        "adapter": args.adapter,
        "stockfish_elo": args.elo,
        "stockfish_path": args.stockfish,
        "stockfish_move_time_ms": args.move_time_ms,
        "stockfish_nodes": args.nodes,
        "stockfish_threads": args.threads,
        "stockfish_hash_mb": args.hash_mb,
        "max_move_seconds": args.max_move_seconds,
        "max_plies": args.max_plies,
        "random_seed": args.seed,
        "notes": args.notes,
    }
    if args.game_id:
        kwargs["game_id"] = args.game_id
    return MatchConfig(**kwargs)


def cmd_play(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    if config.protocol is Protocol.VISUAL:
        print("VISUAL protocol is reserved and not implemented yet.", file=sys.stderr)
        return 2
    if config.random_seed is not None:
        random.seed(config.random_seed)

    try:
        ai_player = adapters.create(config.adapter)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        opponent = StockfishOpponent(
            config.stockfish_path,
            elo=config.stockfish_elo,
            move_time_ms=config.stockfish_move_time_ms,
            nodes=config.stockfish_nodes,
            threads=config.stockfish_threads,
            hash_mb=config.stockfish_hash_mb,
        )
    except EngineUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3

    print(_banner(config, opponent))
    try:
        record = Referee(config, ai_player, opponent).run()
    finally:
        opponent.close()
        ai_player.close()

    if args.analyze:
        print("\nRunning post-game analysis (the AI never sees this)...")
        try:
            analyse_record(
                record, stockfish_path=config.stockfish_path, depth=args.depth
            )
        except EngineUnavailable as exc:
            print(f"analysis skipped: {exc}", file=sys.stderr)

    paths = record.save(args.out)
    print(_result_block(record))
    print(f"\nPGN:  {paths['pgn']}\nJSON: {paths['json']}")
    return 0


def _banner(config: MatchConfig, opponent: StockfishOpponent) -> str:
    return (
        "BlunderZero AI Chess Benchmark\n"
        f"  game id        {config.game_id}\n"
        f"  model          {config.model_name} (adapter: {config.adapter})\n"
        f"  protocol       {config.protocol.value}\n"
        f"  AI plays       {config.ai_color.value}\n"
        f"  opponent       Stockfish, requested Elo {config.stockfish_elo}, "
        f"effective {opponent.effective_elo}\n"
        "  the AI player receives no engine output of any kind"
    )


def _result_block(record: GameRecord) -> str:
    summary = game_summary(record)
    lines = [
        "",
        "=" * 72,
        f"Result {record.result} ({summary['ai_outcome']} for {record.config.model_name})",
        f"Termination: {record.termination} {record.termination_detail}".rstrip(),
        f"Plies: {summary['plies']}   AI moves: {summary['ai_moves']}   "
        f"Illegal: {summary['illegal_moves']}",
    ]
    if record.analysis:
        ai = record.analysis["ai"]
        lines.append(
            f"AI accuracy {ai['accuracy']}%   ACPL {ai['average_centipawn_loss']}   "
            f"inaccuracies {ai['inaccuracies']}  mistakes {ai['mistakes']}  "
            f"blunders {ai['blunders']}"
        )
    lines.append("=" * 72)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# analyze / summarize / show
# --------------------------------------------------------------------------


def cmd_analyze(args: argparse.Namespace) -> int:
    paths = _resolve_game_jsons(args.path)
    if not paths:
        print(f"no game.json found under {args.path}", file=sys.stderr)
        return 2
    for path in paths:
        record = GameRecord.load(path)
        if record.analysis and not args.force:
            print(f"{path}: already analysed (use --force to redo)")
            continue
        try:
            analyse_record(
                record, stockfish_path=args.stockfish, depth=args.depth
            )
        except EngineUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 3
        path.write_text(record.to_json() + "\n", encoding="utf-8")
        ai = record.analysis["ai"]
        print(
            f"{path}: accuracy {ai['accuracy']}%  ACPL {ai['average_centipawn_loss']}  "
            f"inaccuracies {ai['inaccuracies']}  mistakes {ai['mistakes']}  "
            f"blunders {ai['blunders']}"
        )
    return 0


def cmd_summarize(args: argparse.Namespace) -> int:
    records = load_records(args.path)
    if not records:
        print(f"no games found under {args.path}", file=sys.stderr)
        return 2
    rows = [game_summary(r) for r in records]
    if args.json:
        print(json.dumps({"games": rows, "aggregate": aggregate(rows)}, indent=2))
        return 0
    print(format_table(rows))
    print()
    for key, value in aggregate(rows).items():
        print(f"{key:32} {value}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    record = GameRecord.load(args.path)
    for turn in record.turns:
        if turn.actor != Actor.AI:
            continue
        print("=" * 72)
        print(f"ply {turn.ply}  ({turn.color})")
        print("-" * 72)
        print(turn.prompt)
        print("-" * 72)
        print(f"raw response: {turn.raw_response!r}")
        print(f"legal: {turn.legal}  played: {turn.san}")
        if turn.rejection_reason:
            print(f"rejected: {turn.rejection_reason}")
    return 0


def _resolve_game_jsons(path: str) -> list[pathlib.Path]:
    target = pathlib.Path(path)
    if target.is_file():
        return [target]
    return sorted(target.glob("**/game.json"))


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bzbench",
        description="Benchmark general purpose AI models at chess, with no engine "
        "and no chess tools available to the model.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="run one benchmark game")
    play.add_argument("--model", required=True, help="name of the AI model under test")
    play.add_argument(
        "--protocol",
        default=Protocol.RAW.value,
        choices=[p.value for p in Protocol],
        help="information protocol (visual is reserved, not implemented)",
    )
    play.add_argument(
        "--color", default=Color.WHITE.value, choices=[c.value for c in Color],
        help="colour the AI plays",
    )
    play.add_argument(
        "--adapter", default="manual", choices=adapters.available(),
        help="how the model is contacted",
    )
    play.add_argument("--elo", type=int, default=1400, help="Stockfish UCI_Elo")
    play.add_argument("--stockfish", default="stockfish", help="path to the engine")
    play.add_argument("--move-time-ms", type=int, default=100,
                      help="opponent search time per move")
    play.add_argument("--nodes", type=int, default=None,
                      help="opponent fixed node count (more reproducible than time)")
    play.add_argument("--threads", type=int, default=1)
    play.add_argument("--hash-mb", type=int, default=16)
    play.add_argument("--game-id", default=None)
    play.add_argument("--max-move-seconds", type=float, default=None,
                      help="AI response budget; exceeding it is a time forfeit")
    play.add_argument("--max-plies", type=int, default=400)
    play.add_argument("--seed", type=int, default=None)
    play.add_argument("--notes", default="")
    play.add_argument("--out", default=DEFAULT_GAMES_DIR, help="output directory")
    play.add_argument("--analyze", action="store_true",
                      help="run the post-game analysis pass when the game ends")
    play.add_argument("--depth", type=int, default=16,
                      help="post-game analysis depth")
    play.set_defaults(func=cmd_play)

    analyze = sub.add_parser("analyze", help="post-game Stockfish analysis")
    analyze.add_argument("path", help="game.json or a directory of games")
    analyze.add_argument("--stockfish", default="stockfish")
    analyze.add_argument("--depth", type=int, default=16)
    analyze.add_argument("--force", action="store_true", help="re-analyse")
    analyze.set_defaults(func=cmd_analyze)

    summarize = sub.add_parser("summarize", help="summary statistics")
    summarize.add_argument("path", nargs="?", default=DEFAULT_GAMES_DIR)
    summarize.add_argument("--json", action="store_true")
    summarize.set_defaults(func=cmd_summarize)

    show = sub.add_parser("show", help="audit every prompt the AI received")
    show.add_argument("path", help="path to a game.json")
    show.set_defaults(func=cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
