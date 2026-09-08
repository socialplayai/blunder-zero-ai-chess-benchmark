"""Publish a closed game record as immutable evidence.

Working experiment output is not published evidence. `games/` stays untracked
and holds whatever an operator produced, including rehearsals and interrupted
runs. `results/<pilot>/<slot>/` is tracked, is written once, and holds only the
artifacts needed to reproduce and defend a result.

    python3 tools/publish_game.py games/<id>/game.json \
        --pilot api-pilot-v0.1 --slot game-001

Refuses to publish an unfinished record and refuses to overwrite a published
one. Sanitises the operator's hostname and scrubs anything key shaped, then
writes a manifest with a sha256 of every artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bzbench.record import NON_CHESS_TERMINATIONS, GameRecord  # noqa: E402
from bzbench.stats import game_summary  # noqa: E402

SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
HOST_REPLACEMENT = "redacted-host"


class NotPublishable(RuntimeError):
    pass


def scrub(text: str) -> str:
    return SECRET_PATTERN.sub("sk-***REDACTED***", text)


def sanitise_record(data: dict, hostname: str | None) -> tuple[dict, list[str]]:
    """Remove the operator's machine identity. Nothing else is altered."""
    log: list[str] = []
    blob = json.dumps(data, ensure_ascii=False)
    if hostname and hostname in blob:
        blob = blob.replace(hostname, HOST_REPLACEMENT)
        log.append(f"replaced hostname with {HOST_REPLACEMENT!r}")
    scrubbed = scrub(blob)
    if scrubbed != blob:
        log.append("redacted key shaped strings")
    return json.loads(scrubbed), log


def sanitise_pgn(pgn: str, hostname: str | None) -> tuple[str, list[str]]:
    log: list[str] = []
    if hostname and hostname in pgn:
        pgn = pgn.replace(hostname, HOST_REPLACEMENT)
        log.append(f"replaced hostname in the PGN Site header with {HOST_REPLACEMENT!r}")
    scrubbed = scrub(pgn)
    if scrubbed != pgn:
        log.append("redacted key shaped strings in the PGN")
    return scrubbed, log


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:  # pragma: no cover - git missing
        return ""


def check_publishable(record: GameRecord) -> None:
    if not record.finished_at or not record.termination:
        raise NotPublishable(
            "the record is not closed: publish only a game that reached a "
            "termination"
        )
    if record.result == "*" and record.termination not in NON_CHESS_TERMINATIONS:
        raise NotPublishable(
            f"record has no result and an unexpected termination "
            f"{record.termination!r}"
        )


def publish(
    source: pathlib.Path,
    pilot: str,
    slot: str,
    *,
    results_root: pathlib.Path | None = None,
    hostname: str | None = None,
    force: bool = False,
) -> pathlib.Path:
    record = GameRecord.load(source)
    check_publishable(record)

    root = (results_root or (REPO / "results")) / pilot / slot
    if root.exists() and any(root.iterdir()) and not force:
        raise NotPublishable(
            f"{root} already holds a published game; published evidence is "
            "immutable, publish to a new slot instead"
        )
    root.mkdir(parents=True, exist_ok=True)

    if hostname is None:
        import platform

        hostname = platform.node()

    raw = json.loads(source.read_text(encoding="utf-8"))
    sanitised, sanitisation_log = sanitise_record(raw, hostname)

    pgn_source = source.with_name("game.pgn")
    pgn, pgn_log = sanitise_pgn(pgn_source.read_text(encoding="utf-8"), hostname)
    sanitisation_log += pgn_log

    summary = game_summary(record)
    summary["hostname"] = HOST_REPLACEMENT

    (root / "game.json").write_text(
        json.dumps(sanitised, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (root / "game.pgn").write_text(pgn, encoding="utf-8")
    (root / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    config = record.config
    analysis = record.analysis or {}
    api = record.api or {}
    manifest = {
        "pilot": pilot,
        "slot": slot,
        "game_id": config.game_id,
        "published_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(timespec="seconds"),
        "benchmark_commit_recorded_in_game": record.environment.get("bzbench_commit"),
        "benchmark_commit_at_publish": git("rev-parse", "HEAD"),
        "working_tree_clean_at_publish": git("status", "--porcelain") == "",
        "experiment": {
            "model": config.model_name,
            "api_model": config.api_model,
            "adapter": config.adapter,
            "reasoning_effort": config.reasoning_effort,
            "protocol": config.protocol.value,
            "prompt_version": (record.turns[0].view or {}).get("prompt_version")
            if record.turns
            else None,
            "ai_color": config.ai_color.value,
            "max_output_tokens": config.api_max_output_tokens,
            "max_cost_usd": config.max_cost_usd,
            "store": config.api_store,
        },
        "opponent": record.opponent,
        "outcome": {
            "result": record.result,
            "ai_outcome": record.ai_outcome(),
            "termination": record.termination,
            "plies": len([t for t in record.turns if t.uci]),
            "illegal_moves": len(record.illegal_moves),
            "infrastructure_failure": record.infrastructure_failure,
        },
        "analysis": {
            "engine": analysis.get("engine"),
            "ai": analysis.get("ai"),
            "opponent": analysis.get("opponent"),
        },
        "usage": {
            key: api.get(key)
            for key in (
                "calls", "input_tokens", "cached_input_tokens", "output_tokens",
                "reasoning_tokens", "total_tokens", "input_cost_usd",
                "output_cost_usd", "total_cost_usd", "max_output_tokens",
            )
        },
        "pricing": api.get("pricing"),
        "sanitisation": sanitisation_log or ["nothing to redact"],
        "artifacts": {
            name: {"sha256": sha256(root / name), "bytes": (root / name).stat().st_size}
            for name in ("game.json", "game.pgn", "summary.json")
        },
        "verification": {
            "how_to_reproduce": (
                f"check out {record.environment.get('bzbench_commit')} and run the "
                "command in docs/api-pilot-v0.1.md for this slot; the opponent is "
                "reproducible at a fixed node count, the model is not"
            ),
            "integrity_note": (
                "game.json contains every prompt sent and every raw response "
                "received, so the protocol claims in the README can be rechecked "
                "against the record without trusting this manifest"
            ),
        },
    }
    (root / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="path to a closed games/<id>/game.json")
    parser.add_argument("--pilot", required=True, help="e.g. api-pilot-v0.1")
    parser.add_argument("--slot", required=True, help="e.g. game-001")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an already published slot (avoid)")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    try:
        destination = publish(
            pathlib.Path(args.source), args.pilot, args.slot, force=args.force
        )
    except NotPublishable as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    print(f"published to {destination}")
    for item in sorted(destination.iterdir()):
        print(f"  {item.name}")
