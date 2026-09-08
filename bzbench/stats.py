"""Summary statistics for one game and for a set of games."""

from __future__ import annotations

import pathlib
from typing import Any, Iterable

from .record import Actor, GameRecord


def game_summary(record: GameRecord) -> dict[str, Any]:
    """The per-game row of the benchmark table."""
    ai_moves = [t for t in record.turns if t.actor == Actor.AI and t.uci]
    response_times = [
        t.response_seconds for t in record.turns
        if t.actor == Actor.AI and t.response_seconds is not None
    ]
    responses = [t for t in record.turns if t.actor == Actor.AI and t.legal is not None]
    malformed = [
        item for item in record.illegal_moves
        if item.get("reason") in {
            "empty response",
            "response contains more than one token",
            "not valid standard algebraic notation",
        }
    ]
    illegal_but_well_formed = [
        item for item in record.illegal_moves
        if item.get("reason") in {
            "move is not legal in this position",
            "ambiguous SAN, matches more than one legal move",
        }
    ]
    summary: dict[str, Any] = {
        "game_id": record.config.game_id,
        "model": record.config.model_name,
        "adapter": record.config.adapter,
        "protocol": record.config.protocol.value,
        "ai_color": record.config.ai_color.value,
        "stockfish_elo": record.effective_elo(),
        "result": record.result,
        "ai_outcome": record.ai_outcome(),
        "win": int(record.ai_outcome() == "win"),
        "draw": int(record.ai_outcome() == "draw"),
        "loss": int(record.ai_outcome() == "loss"),
        "termination": record.termination,
        "termination_detail": record.termination_detail,
        "plies": len([t for t in record.turns if t.uci]),
        "ai_moves": len(ai_moves),
        "illegal_moves": len(record.illegal_moves),
        # Protocol reliability, kept separate from chess quality on purpose.
        "ai_responses": len(responses),
        "legal_responses": sum(1 for t in responses if t.legal),
        "malformed_responses": len(malformed),
        # Observational categories only. "illegal_move_responses" records what
        # was observed (well formed SAN, not legal here); the cause is not
        # claimed by the field name. See docs/reporting-dimensions.md.
        "illegal_move_responses": len(illegal_but_well_formed),
        "first_illegal_ply": (
            record.illegal_moves[0]["ply"] if record.illegal_moves else None
        ),
        "median_ai_response_seconds": _median(response_times),
        "started_at": record.started_at,
        "finished_at": record.finished_at,
    }
    api = record.api or {}
    summary.update(
        {
            "api_calls": api.get("calls"),
            "total_tokens": api.get("total_tokens"),
            "reasoning_tokens": api.get("reasoning_tokens"),
            "total_cost_usd": api.get("total_cost_usd"),
            "infrastructure_failure": (
                (record.infrastructure_failure or {}).get("kind")
            ),
        }
    )
    analysis = record.analysis or {}
    ai_analysis = analysis.get("ai") or {}
    summary.update(
        {
            "accuracy": ai_analysis.get("accuracy"),
            "average_centipawn_loss": ai_analysis.get("average_centipawn_loss"),
            "inaccuracies": ai_analysis.get("inaccuracies"),
            "mistakes": ai_analysis.get("mistakes"),
            "blunders": ai_analysis.get("blunders"),
            "analysed": bool(analysis),
        }
    )
    return summary


def aggregate(summaries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-game rows into a benchmark result."""
    rows = list(summaries)
    if not rows:
        return {"games": 0}
    finished = [r for r in rows if r["ai_outcome"] != "unfinished"]
    scored = [r for r in rows if r["accuracy"] is not None]
    wins = sum(r["win"] for r in rows)
    draws = sum(r["draw"] for r in rows)
    losses = sum(r["loss"] for r in rows)
    return {
        "games": len(rows),
        "finished_games": len(finished),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "score_rate": round((wins + 0.5 * draws) / len(finished), 3) if finished else None,
        "games_with_illegal_move": sum(1 for r in rows if r["illegal_moves"]),
        "total_illegal_moves": sum(r["illegal_moves"] for r in rows),
        "total_ai_responses": sum(r["ai_responses"] for r in rows),
        "total_legal_responses": sum(r["legal_responses"] for r in rows),
        "total_malformed_responses": sum(r["malformed_responses"] for r in rows),
        "total_illegal_move_responses": sum(
            r["illegal_move_responses"] for r in rows
        ),
        "legal_response_rate": (
            round(
                sum(r["legal_responses"] for r in rows)
                / sum(r["ai_responses"] for r in rows),
                4,
            )
            if sum(r["ai_responses"] for r in rows)
            else None
        ),
        "mean_plies": round(sum(r["plies"] for r in rows) / len(rows), 1),
        "mean_accuracy": (
            round(sum(r["accuracy"] for r in scored) / len(scored), 2) if scored else None
        ),
        "mean_average_centipawn_loss": (
            round(
                sum(r["average_centipawn_loss"] for r in scored) / len(scored), 1
            )
            if scored
            else None
        ),
        "total_api_cost_usd": round(
            sum(r["total_cost_usd"] or 0.0 for r in rows), 6
        ),
        "total_api_tokens": sum(r["total_tokens"] or 0 for r in rows),
        "infrastructure_failures": sum(
            1 for r in rows if r["infrastructure_failure"]
        ),
        "terminations": _counts(r["termination"] for r in rows),
        "protocols": _counts(r["protocol"] for r in rows),
        "models": _counts(r["model"] for r in rows),
        "stockfish_elos": _counts(str(r["stockfish_elo"]) for r in rows),
    }


def load_records(root: str | pathlib.Path) -> list[GameRecord]:
    """Load every game.json under `root`."""
    root = pathlib.Path(root)
    if root.is_file():
        return [GameRecord.load(root)]
    return [GameRecord.load(p) for p in sorted(root.glob("**/game.json"))]


def format_table(rows: list[dict[str, Any]]) -> str:
    columns = [
        ("game_id", 12),
        ("model", 18),
        ("protocol", 8),
        ("ai_color", 6),
        ("elo", 5),
        ("result", 7),
        ("outcome", 10),
        ("plies", 5),
        ("illegal", 7),
        ("acpl", 6),
        ("acc%", 6),
        ("cost$", 7),
        ("termination", 20),
    ]
    key_map = {
        "elo": "stockfish_elo",
        "outcome": "ai_outcome",
        "illegal": "illegal_moves",
        "acpl": "average_centipawn_loss",
        "acc%": "accuracy",
        "cost$": "total_cost_usd",
    }
    columns = [(name, max(width, len(name))) for name, width in columns]
    header = "  ".join(name.ljust(width) for name, width in columns)
    lines = [header, "-" * len(header)]
    for row in rows:
        cells = []
        for name, width in columns:
            value = row.get(key_map.get(name, name))
            text = "-" if value is None else str(value)
            cells.append(text[:width].ljust(width))
        lines.append("  ".join(cells))
    return "\n".join(lines)


def _counts(values: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = "unknown" if value is None else str(value)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 2)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)
