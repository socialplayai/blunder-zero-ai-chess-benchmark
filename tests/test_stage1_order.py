"""The Stage 1 half must be defined, balanced, and must not touch the corpus."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import stage1_order  # noqa: E402

CORPUS = REPO / "results/diagnostics/reliability-study-v0.1/corpus.json"


@pytest.fixture(scope="module")
def corpus():
    if not CORPUS.exists():
        pytest.skip("the corpus is not frozen in this checkout")
    return json.loads(CORPUS.read_text())


@pytest.fixture(scope="module")
def order(corpus):
    return stage1_order.build(corpus, 20260908)


def test_stage1_hits_every_target(order):
    achieved = order["stage1_achieved"]
    assert achieved["n"] == 20
    assert achieved["source_protocol"] == {"raw": 8, "fen": 12}
    assert achieved["side_to_move"] == {"white": 10, "black": 10}
    assert achieved["depth_bins"] == {"early": 7, "middle": 6, "late": 7}
    assert sorted(achieved["per_game"].values()) == [3, 3, 3, 3, 4, 4]
    assert all(n > 0 for n in achieved["per_game"].values())


def test_the_two_stages_partition_the_corpus_exactly(corpus, order):
    keys = {stage1_order.key(p) for p in corpus["positions"]}
    stage1, stage2 = set(order["stage1"]), set(order["stage2"])
    assert stage1 | stage2 == keys
    assert stage1 & stage2 == set()
    assert len(order["stage1"]) == len(order["stage2"]) == 20


def test_a_naive_file_order_would_have_been_skewed(corpus):
    """The reason this amendment exists, asserted rather than asserted about."""
    naive = corpus["positions"][:20]
    protocols = {p["source_protocol"] for p in naive}
    assert protocols == {"fen"}          # 20 FEN, 0 RAW
    assert len({p["game_id"] for p in naive}) < 6


def test_the_corpus_is_untouched_and_pinned(corpus, order):
    assert order["corpus_sha256"] == hashlib.sha256(CORPUS.read_bytes()).hexdigest()
    # No position content lives in the order file, only keys into the corpus.
    blob = json.dumps(order)
    assert "fen" in blob  # the protocol label
    for position in corpus["positions"]:
        assert position["fen"] not in blob
        assert position["response_id"] not in blob


def test_no_engine_information_enters_the_ordering(order):
    blob = json.dumps(order).lower()
    for term in ("centipawn", "accuracy", "acpl", "judgement", "blunder"):
        assert term not in blob


def test_ordering_is_deterministic_for_a_seed(corpus, order):
    again = stage1_order.build(corpus, 20260908)
    assert again["stage1"] == order["stage1"]
    assert again["stage2"] == order["stage2"]


def test_the_frozen_order_is_never_rewritten(tmp_path):
    out = tmp_path / "stage1.json"
    out.write_text("{}")
    result = subprocess.run(
        [sys.executable, "tools/stage1_order.py", "--corpus", str(CORPUS),
         "--out", str(out)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "frozen once" in result.stderr
    assert out.read_text() == "{}"
