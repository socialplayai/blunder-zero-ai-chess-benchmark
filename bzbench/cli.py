"""Command line interface.

    bzbench play      run one benchmark game
    bzbench analyze   post-game Stockfish analysis of a saved game
    bzbench summarize summary statistics over saved games
    bzbench show      audit what a game showed the AI player
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import sys
from typing import Any

from . import adapters
from .adapters.base import AuthenticationFailure, PlayerInfrastructureError
from .adapters.openai_api import (
    DEFAULT_API_KEY_ENV,
    REASONING_EFFORTS,
    ReasoningEffortNotSupported,
    build_client,
    validate_reasoning_effort,
)
from .analysis import analyse_record
from .config import Color, MatchConfig, Protocol
from .engine import EngineUnavailable, StockfishOpponent
from .pricing import (
    Pricing,
    PricingError,
    cost_of,
    estimate_game_cost,
    extract_usage,
)
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
        "api_model": args.api_model,
        "reasoning_effort": args.reasoning_effort,
        "api_store": not args.no_store,
        "api_service_tier": args.service_tier,
        "api_max_output_tokens": args.max_output_tokens,
        "api_request_timeout_seconds": args.request_timeout,
        "api_max_attempts": args.max_attempts,
        "api_backoff_seconds": args.backoff_seconds,
        "pricing_file": args.pricing_file,
        "max_cost_usd": args.max_cost_usd,
        "max_total_tokens": args.max_total_tokens,
        "max_move_seconds": args.max_move_seconds,
        "max_plies": args.max_plies,
        "random_seed": args.seed,
        "notes": args.notes,
    }
    if args.game_id:
        kwargs["game_id"] = args.game_id
    return MatchConfig(**kwargs)


def load_pricing(config: MatchConfig) -> Pricing:
    if config.pricing_file:
        return Pricing.load(config.pricing_file)
    return Pricing.for_model(config.api_model)


def build_player(config: MatchConfig, client: Any | None = None):
    """Build the AI player for `config`. Secrets come from the environment."""
    if config.adapter != "openai":
        return adapters.create(config.adapter)
    return adapters.create(
        "openai",
        model=config.api_model,
        reasoning_effort=config.reasoning_effort,
        pricing=load_pricing(config),
        max_cost_usd=config.max_cost_usd,
        max_total_tokens=config.max_total_tokens,
        max_output_tokens=config.api_max_output_tokens,
        store=config.api_store,
        service_tier=config.api_service_tier,
        request_timeout=config.api_request_timeout_seconds,
        max_attempts=config.api_max_attempts,
        backoff_seconds=config.api_backoff_seconds,
        game_id=config.game_id,
        client=client,
    )


def cmd_play(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    if config.protocol is Protocol.VISUAL:
        print("VISUAL protocol is reserved and not implemented yet.", file=sys.stderr)
        return 2
    if config.random_seed is not None:
        random.seed(config.random_seed)

    try:
        ai_player = build_player(config)
    except (ValueError, PricingError, ReasoningEffortNotSupported) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except AuthenticationFailure as exc:
        print(str(exc), file=sys.stderr)
        return 4

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
        + (
            f"  api model      {config.api_model}, reasoning {config.reasoning_effort},"
            f" no tools\n"
            f"  spend guard    "
            f"{'$%.2f per game' % config.max_cost_usd if config.max_cost_usd else 'none'}"
            f"{', %d tokens' % config.max_total_tokens if config.max_total_tokens else ''}\n"
            if config.adapter == "openai"
            else ""
        )
        + "  the AI player receives no engine output of any kind"
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
    if record.api:
        api = record.api
        lines.append(
            f"API calls {api['calls']}   tokens {api['total_tokens']}   "
            f"reasoning {api['reasoning_tokens']}   "
            f"cost ${api['total_cost_usd']:.4f}"
        )
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
# preflight
# --------------------------------------------------------------------------


class Check:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, ok, detail))
        return ok

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.rows)

    def render(self) -> str:
        width = max(len(name) for name, _, _ in self.rows)
        lines = []
        for name, ok, detail in self.rows:
            mark = "PASS" if ok else "FAIL"
            lines.append(f"  [{mark}] {name.ljust(width)}  {detail}".rstrip())
        return "\n".join(lines)


def cmd_preflight(args: argparse.Namespace) -> int:
    """Verify everything a real run needs, without playing a game."""
    checks = Check()
    print("Preflight for the BlunderZero AI chess benchmark\n")

    # 1. Configuration.
    config = None
    try:
        config = _config_from_args(args)
        checks.add("benchmark configuration", True,
                   f"{config.protocol.value} protocol, AI plays {config.ai_color.value}")
    except (ValueError, TypeError) as exc:
        checks.add("benchmark configuration", False, str(exc))

    if config is not None and config.protocol is Protocol.VISUAL:
        checks.add("protocol implemented", False, "visual is reserved")

    # 2. Output directory.
    out = pathlib.Path(args.out)
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe_path = out / ".preflight-write-test"
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink()
        checks.add("output directory writable", True, str(out.resolve()))
    except OSError as exc:
        checks.add("output directory writable", False, str(exc))

    # 3. Stockfish.
    if config is not None:
        try:
            opponent = StockfishOpponent(
                config.stockfish_path,
                elo=config.stockfish_elo,
                move_time_ms=config.stockfish_move_time_ms,
                nodes=config.stockfish_nodes,
                threads=config.stockfish_threads,
                hash_mb=config.stockfish_hash_mb,
            )
            description = opponent.describe()
            opponent.close()
            checks.add(
                "stockfish available", True,
                f"{description.engine_name}, requested Elo {description.requested_elo}, "
                f"effective {description.effective_elo}, limit {description.limit}",
            )
        except EngineUnavailable as exc:
            checks.add("stockfish available", False, str(exc))

    if config is not None and config.adapter != "openai":
        print(checks.render())
        print("\nAdapter is not the API player, so no provider checks were run.")
        return 0 if checks.ok else 1

    # 4. Pricing metadata.
    pricing = None
    if config is not None:
        try:
            pricing = load_pricing(config)
            checks.add(
                "pricing metadata", True,
                f"${pricing.input_per_mtok}/${pricing.cached_input_per_mtok}/"
                f"${pricing.output_per_mtok} per Mtok in/cached/out, verified "
                f"{pricing.verified_at} ({pricing.age_days():.1f} days ago), "
                f"{pricing.source}",
            )
        except PricingError as exc:
            checks.add("pricing metadata", False, str(exc))

    # 5. Reasoning level, checked locally before anything is sent.
    effort_ok = False
    if config is not None:
        try:
            validate_reasoning_effort(config.api_model, config.reasoning_effort)
            effort_ok = checks.add(
                "reasoning effort allowed", True,
                f"{config.reasoning_effort} on {config.api_model}",
            )
        except ReasoningEffortNotSupported as exc:
            checks.add("reasoning effort allowed", False, str(exc))

    # 6. API key presence. The value is never printed.
    key_present = bool(os.environ.get(DEFAULT_API_KEY_ENV))
    checks.add("API key in environment", key_present,
               f"{DEFAULT_API_KEY_ENV} is {'set' if key_present else 'missing'}")

    # 7. Model access and, optionally, a tiny probe generation.
    client = None
    if key_present and config is not None and effort_ok:
        try:
            client = build_client()
            model = client.models.retrieve(config.api_model)
            checks.add("model accessible", True,
                       f"{getattr(model, 'id', config.api_model)}")
        except Exception as exc:  # noqa: BLE001
            checks.add("model accessible", False, _scrub(str(exc)))

    if client is not None and args.probe and checks.ok:
        try:
            player = build_player(config, client=client)
            request = player._build_request("ping", _probe_view(config))
            request["input"] = "Reply with the single character: x"
            request["max_output_tokens"] = args.probe_max_output_tokens
            request.pop("previous_response_id", None)
            response = client.responses.create(
                timeout=config.api_request_timeout_seconds, **request
            )
            usage = extract_usage(_usage_dict(response))
            cost = cost_of(usage, pricing) if pricing else None
            checks.add(
                "reasoning setting accepted by the API", True,
                f"status {getattr(response, 'status', '?')}, "
                f"{usage['total_tokens']} tokens"
                + (f", ${cost.total_cost_usd:.6f}" if cost else ""),
            )
            checks.add("no tools in the request", request.get("tools") == [],
                       "tools=[] and no tool_choice")
        except Exception as exc:  # noqa: BLE001
            checks.add("reasoning setting accepted by the API", False, _scrub(str(exc)))
    elif client is not None and not args.probe:
        checks.add("reasoning setting accepted by the API", True,
                   "skipped, --no-probe (validated locally only)")

    # 8. Static proof that the request carries no tools.
    if config is not None and pricing is not None and effort_ok:
        sample = adapters.create(
            "openai", model=config.api_model,
            reasoning_effort=config.reasoning_effort, pricing=pricing,
            client=_NullClient(), game_id=config.game_id,
            max_cost_usd=config.max_cost_usd,
            max_total_tokens=config.max_total_tokens,
            store=config.api_store,
        )
        request = sample._build_request("prompt", _probe_view(config))
        no_tools = request.get("tools") == [] and "tool_choice" not in request
        checks.add("request exposes no tools", no_tools, f"tools={request.get('tools')}")

    print(checks.render())

    if pricing is not None:
        estimate = estimate_game_cost(
            pricing,
            moves=args.estimate_moves,
            input_tokens_per_move=args.estimate_input_tokens,
            output_tokens_per_move=args.estimate_output_tokens,
        )
        print("\nUpper bound cost estimate for one game (no caching assumed):")
        for key, value in estimate.items():
            print(f"  {key:34} {value}")
        if config is not None and config.max_cost_usd is not None:
            verdict = (
                "the spend guard stops the game first"
                if estimate["total_cost_usd"] > config.max_cost_usd
                else "the estimate is inside the guard"
            )
            print(f"  {'spend guard':34} ${config.max_cost_usd:.2f} ({verdict})")

    print("\nPreflight " + ("PASSED" if checks.ok else "FAILED"))
    return 0 if checks.ok else 1


class _NullClient:
    """Stands in for a client when only the request shape is being inspected."""

    class _Responses:
        def create(self, **kwargs):  # pragma: no cover - never called
            raise AssertionError("preflight must not generate through _NullClient")

    responses = _Responses()


def _probe_view(config: MatchConfig):
    from .protocol import build_turn_view

    import chess

    return build_turn_view(chess.Board(), [], config.protocol, config.ai_color)


def _usage_dict(response: Any) -> dict | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    dump = getattr(usage, "model_dump", None)
    return dump() if callable(dump) else dict(usage)


def _scrub(text: str) -> str:
    from .adapters.openai_api import scrub_secrets

    return scrub_secrets(text)


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


def add_api_arguments(parser: argparse.ArgumentParser) -> None:
    """Options for the openai adapter. No option ever carries a secret."""
    group = parser.add_argument_group("openai adapter")
    group.add_argument("--api-model", default="gpt-6-astra",
                       help="exact provider model identifier")
    group.add_argument("--reasoning-effort", default="high",
                       choices=list(REASONING_EFFORTS),
                       help="reasoning effort; never silently downgraded")
    group.add_argument("--max-output-tokens", type=int, default=None,
                       help="cap on output tokens per move; unset by default so a "
                            "truncated answer cannot be mistaken for a bad move")
    group.add_argument("--service-tier", default=None)
    group.add_argument("--no-store", action="store_true",
                       help="do not keep the response chain server side; this also "
                            "disables cross turn reasoning continuity")
    group.add_argument("--request-timeout", type=float, default=900.0)
    group.add_argument("--max-attempts", type=int, default=3,
                       help="attempts per move, retries only before a response exists")
    group.add_argument("--backoff-seconds", type=float, default=5.0)
    group.add_argument("--pricing-file", default=None,
                       help="pricing JSON; defaults to pricing/<api-model>.json")
    group.add_argument("--max-cost-usd", type=float, default=15.0,
                       help="per game spend guard; reaching it aborts the game "
                            "without a chess result")
    group.add_argument("--max-total-tokens", type=int, default=None,
                       help="per game token guard")


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
    add_api_arguments(play)
    play.set_defaults(func=cmd_play)

    pre = sub.add_parser(
        "preflight",
        help="verify credentials, model access, engine and configuration "
             "without starting a game",
    )
    pre.add_argument("--model", default="gpt-6-astra",
                     help="label for the run; the API identifier is --api-model")
    pre.add_argument("--protocol", default=Protocol.RAW.value,
                     choices=[p.value for p in Protocol])
    pre.add_argument("--color", default=Color.WHITE.value,
                     choices=[c.value for c in Color])
    pre.add_argument("--adapter", default="openai", choices=adapters.available())
    pre.add_argument("--elo", type=int, default=1320)
    pre.add_argument("--stockfish", default="stockfish")
    pre.add_argument("--move-time-ms", type=int, default=100)
    pre.add_argument("--nodes", type=int, default=None)
    pre.add_argument("--threads", type=int, default=1)
    pre.add_argument("--hash-mb", type=int, default=16)
    pre.add_argument("--game-id", default=None)
    pre.add_argument("--max-move-seconds", type=float, default=None)
    pre.add_argument("--max-plies", type=int, default=400)
    pre.add_argument("--seed", type=int, default=None)
    pre.add_argument("--notes", default="")
    pre.add_argument("--out", default=DEFAULT_GAMES_DIR)
    pre.add_argument("--probe", action="store_true", default=True,
                     help="send one tiny capped generation to prove the reasoning "
                          "setting is accepted (default on)")
    pre.add_argument("--no-probe", dest="probe", action="store_false")
    pre.add_argument("--probe-max-output-tokens", type=int, default=16)
    pre.add_argument("--estimate-moves", type=int, default=60,
                     help="assumed moves per game for the cost upper bound")
    pre.add_argument("--estimate-input-tokens", type=int, default=2000,
                     help="assumed input tokens per move for the cost upper bound")
    pre.add_argument("--estimate-output-tokens", type=int, default=6000,
                     help="assumed output tokens per move, reasoning included")
    add_api_arguments(pre)
    pre.set_defaults(func=cmd_preflight)

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
