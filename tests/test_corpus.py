"""The frozen corpus must be reproducible, in frame, and immutable."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import build_corpus  # noqa: E402


@pytest.fixture(scope="module")
def corpus():
    for path, _, _ in build_corpus.SOURCES:
        if not (REPO / path).exists():
            pytest.skip("the six published source games are not in this checkout")
    return build_corpus.build(20260908)


def test_the_frame_is_exactly_what_was_preregistered(corpus):
    assert len(corpus["positions"]) == 40
    assert corpus["source_protocol_counts"] == {"raw": 16, "fen": 24}
    quotas = corpus["frame"]["per_game_quotas"]
    assert sorted(quotas.values()) == [6, 6, 6, 6, 8, 8]
    assert len(corpus["sources"]) == 6
    assert corpus["frame"]["selection_used_engine_information"] is False


def test_per_game_quotas_are_met_exactly(corpus):
    counts: dict[str, int] = {}
    for position in corpus["positions"]:
        counts[position["game_id"]] = counts.get(position["game_id"], 0) + 1
    assert counts == corpus["frame"]["per_game_quotas"]


def test_the_separation_rule_holds_within_every_game(corpus):
    used = corpus["frame"]["separation_used"]
    by_game: dict[str, list[int]] = {}
    for position in corpus["positions"]:
        by_game.setdefault(position["game_id"], []).append(position["depth"])
    for game_id, depths in by_game.items():
        depths.sort()
        gaps = [b - a for a, b in zip(depths, depths[1:])]
        assert all(gap >= used[game_id] for gap in gaps), (game_id, depths)
    # The one game preregistered as needing a relaxation, and only that one.
    assert used["API-PILOT-v0.1-g2-astra-black"] == 2
    assert all(v == 3 for k, v in used.items()
               if k != "API-PILOT-v0.1-g2-astra-black")


def test_depth_strata_hit_the_frozen_targets(corpus):
    assert corpus["depth_counts"] == {"early": 13, "middle": 13, "late": 14}
    assert corpus["depth_shortfall"] == 0
    for position in corpus["positions"]:
        assert position["depth"] >= build_corpus.MIN_DEPTH
        assert position["depth_bin"] == build_corpus.depth_bin(position["depth"])


def test_every_game_contributes_across_the_depths_it_contains(corpus):
    by_game: dict[str, set[str]] = {}
    for position in corpus["positions"]:
        by_game.setdefault(position["game_id"], set()).add(position["depth_bin"])
    # The short RAW game has only two late candidates; every other game spans all
    # three bins rather than the bins being satisfied by one or two long games.
    for game_id, bins in by_game.items():
        assert len(bins) >= 2, (game_id, bins)


def test_every_position_can_actually_be_replayed_and_chained(corpus):
    import chess

    for position in corpus["positions"]:
        assert position["response_id"].startswith("resp_")
        board = chess.Board(position["fen"])
        assert board.is_valid()
        assert board.legal_moves.count() == position["features"]["legal_moves"]
        expected = "white" if board.turn else "black"
        assert position["side_to_move"] == expected


def test_no_engine_information_reaches_the_selection(corpus):
    blob = json.dumps(corpus)
    for term in ("centipawn", "accuracy", "acpl", "judgement", "cp_before",
                 "blunder", "analysis"):
        assert term not in blob.lower()


def test_sampling_is_deterministic_for_a_seed(corpus):
    again = build_corpus.build(20260908)
    assert [(p["game_id"], p["depth"]) for p in again["positions"]] == [
        (p["game_id"], p["depth"]) for p in corpus["positions"]
    ]


def test_source_records_are_pinned_by_hash(corpus):
    import hashlib

    for source in corpus["sources"]:
        path = REPO / source["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["record_sha256"]
        assert source["benchmark_commit"]


def test_a_frozen_corpus_is_never_rewritten(tmp_path):
    out = tmp_path / "corpus.json"
    out.write_text("{}")
    result = subprocess.run(
        [sys.executable, "tools/build_corpus.py", "--out", str(out)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "never rewritten" in result.stderr
    assert out.read_text() == "{}"
