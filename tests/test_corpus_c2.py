"""Amendment C2: prove the chain parent is the right one, not merely a different one.

A test that only asserts `chain_from_response_id != response_id` would forbid the
observed bug and permit a dozen others. These assert what the parent must *be*.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import amend_corpus_c2 as c2  # noqa: E402
from failure_probe import state_at_ply  # noqa: E402

from bzbench.config import Protocol  # noqa: E402
from bzbench.protocol import build_prompt  # noqa: E402
from bzbench.record import GameRecord  # noqa: E402

STUDY = REPO / "results/diagnostics/reliability-study-v0.1"


@pytest.fixture(scope="module")
def corpus():
    if not (STUDY / "corpus.json").exists():
        pytest.skip("corpus not frozen in this checkout")
    return json.loads((STUDY / "corpus.json").read_text())


@pytest.fixture(scope="module")
def records(corpus):
    return {p["source_path"]: GameRecord.load(REPO / p["source_path"])
            for p in corpus["positions"]}


def model_turns(record):
    return c2.model_turns(record)


def test_c2_is_applied_to_every_position(corpus):
    assert any(a["id"] == "C2" for a in corpus["amendments"])
    for position in corpus["positions"]:
        assert position["chain_from_response_id"]
        assert isinstance(position["chain_from_ply"], int)


# ------------------------------------------------------------ invariant 1

def test_current_response_id_is_the_sampled_turns_own_response(corpus, records):
    for position in corpus["positions"]:
        record = records[position["source_path"]]
        turn = next(t for t in record.turns
                    if t.ply == position["ply"] and t.actor == "ai")
        assert turn.api["response_id"] == position["response_id"]


# --------------------------------------------------------- invariants 2, 3

def test_the_parent_is_the_immediately_preceding_model_turn(corpus, records):
    for position in corpus["positions"]:
        record = records[position["source_path"]]
        turns = model_turns(record)
        index = next(i for i, t in enumerate(turns) if t.ply == position["ply"])
        assert index >= 1, "a sampled position must have a preceding model turn"
        parent = turns[index - 1]
        assert position["chain_from_response_id"] == parent.api["response_id"]
        assert position["chain_from_ply"] == parent.ply
        # Nothing may sit between them in the model's own turn sequence.
        assert turns[index].ply == position["ply"]
        between = [t for t in turns
                   if parent.ply < t.ply < position["ply"]]
        assert between == []


def test_the_parent_link_matches_what_the_game_itself_recorded(corpus, records):
    """The record's own previous_response_id is an independent witness."""
    for position in corpus["positions"]:
        record = records[position["source_path"]]
        turn = next(t for t in record.turns
                    if t.ply == position["ply"] and t.actor == "ai")
        assert turn.api["previous_response_id"] == position["chain_from_response_id"]


# ------------------------------------------------------------ invariant 4

def test_the_parent_context_cannot_contain_the_sampled_prompt_or_answer(
    corpus, records
):
    for position in corpus["positions"]:
        record = records[position["source_path"]]
        turns = model_turns(record)
        index = next(i for i, t in enumerate(turns) if t.ply == position["ply"])
        parent, sampled = turns[index - 1], turns[index]

        # The parent is strictly earlier in the game.
        assert parent.ply < sampled.ply
        # The parent was asked a different question about an earlier board.
        assert parent.prompt != sampled.prompt
        assert parent.fen_before != sampled.fen_before
        # The sampled prompt was produced after the parent existed, so it cannot
        # be inside the parent's context.
        assert sampled.prompt not in (parent.prompt or "")
        # The sound check: the parent's history is a strict prefix of the
        # sampled turn's history, and the sampled answer is not among the moves
        # added in between. A substring test on SAN would be unsound, because
        # the same SAN token recurs across a game.
        parent_board, parent_history, _ = state_at_ply(record, parent.ply)
        sampled_board, sampled_history, _ = state_at_ply(record, sampled.ply)
        assert len(parent_history) < len(sampled_history)
        assert sampled_history[:len(parent_history)] == parent_history
        added = sampled_history[len(parent_history):]
        assert len(added) >= 1          # at least the parent's own move
        assert parent_board.fen() != sampled_board.fen()
        # Deliberately NOT asserted: that the sampled SAN differs from any move
        # in `added`, or from the parent's answer. In a repetition or a shuffle a
        # model legitimately plays the same SAN again a move later, and the move
        # history is protocol content the prompt is supposed to contain. Textual
        # SAN equality is not an information leak; the structural checks above
        # are what bound the context.


def test_no_later_move_fen_or_analysis_can_be_in_the_parent_context(corpus, records):
    for position in corpus["positions"]:
        record = records[position["source_path"]]
        parent_ply = position["chain_from_ply"]
        parent = next(t for t in record.turns
                      if t.ply == parent_ply and t.actor == "ai")
        later = [t for t in record.turns if t.ply > parent_ply and t.san]
        prompt = parent.prompt or ""
        # No board reached after the parent turn appears in its prompt.
        for turn in later:
            assert turn.fen_before not in prompt
        # Analysis is post game and never enters any prompt.
        for term in ("centipawn", "accuracy", "acpl", "blunder", "evaluation"):
            assert term not in prompt.lower()


# ------------------------------------------------------------ invariant 5

def test_the_boundary_matches_the_original_ply45_diagnostic():
    """C2 reproduces exactly what --chain-from-ply 43 did for ply 45."""
    published = REPO / "results/api-pilot-v0.1/game-002/game.json"
    diagnostic = REPO / "results/diagnostics/api-pilot-v0.1-g2-ply45/chain-arms.json"
    if not (published.exists() and diagnostic.exists()):
        pytest.skip("the ply 45 diagnostic is not in this checkout")
    record = GameRecord.load(published)
    parent_ply, parent_id = c2.parent_of(record, 45)
    assert parent_ply == 43
    payload = json.loads(diagnostic.read_text())
    assert payload["chain_from_ply"] == 43
    assert payload["chain_from_response_id"] == parent_id


# ------------------------------------------------------------ invariant 6

def test_a_chain_arm_can_never_branch_from_a_wrong_response(corpus, records):
    by_game_ids = {
        path: {t.api["response_id"] for t in model_turns(record)}
        for path, record in records.items()
    }
    for position in corpus["positions"]:
        record = records[position["source_path"]]
        parent_id = position["chain_from_response_id"]
        # not its own
        assert parent_id != position["response_id"]
        # not a later one
        later = {t.api["response_id"] for t in model_turns(record)
                 if t.ply >= position["ply"]}
        assert parent_id not in later
        # belongs to this game and no other
        assert parent_id in by_game_ids[position["source_path"]]
        for path, ids in by_game_ids.items():
            if path != position["source_path"]:
                assert parent_id not in ids


# ------------------------------------------------- what C2 did not change

def test_c2_changed_nothing_but_the_two_new_fields(corpus):
    added = {"chain_from_response_id", "chain_from_ply"}
    for position in corpus["positions"]:
        expected = {
            "ply", "depth", "depth_bin", "fen", "side_to_move", "response_id",
            "history_length", "features", "game_id", "source_protocol",
            "source_path",
        } | added
        assert set(position) == expected
    assert corpus["depth_counts"] == {"early": 13, "middle": 13, "late": 14}
    assert corpus["source_protocol_counts"] == {"raw": 16, "fen": 24}
    assert corpus["side_to_move_counts"] == {"white": 20, "black": 20}
    assert corpus["seed"] == 20260908
    assert len(corpus["positions"]) == 40


def test_the_stage_one_ordering_survived_c2_unchanged():
    import hashlib

    import stage1_order

    corpus = json.loads((STUDY / "corpus.json").read_text())
    frozen = json.loads((STUDY / "stage1-order.json").read_text())
    regenerated = stage1_order.build(corpus, frozen["seed"])
    assert regenerated["stage1"] == frozen["stage1"]
    assert regenerated["stage2"] == frozen["stage2"]
    assert frozen["corpus_sha256"] == hashlib.sha256(
        (STUDY / "corpus.json").read_bytes()
    ).hexdigest()
    assert frozen["corpus_sha256_pre_c2"] != frozen["corpus_sha256"]


def test_the_corpus_contains_the_known_failure_position_and_says_so():
    """Disclosure, not a defect: blind sampling drew the ply 45 position.

    It is 1 of 40, it was selected by the frozen frame before anyone looked, and
    removing it after noticing would be post hoc selection, which is worse than
    keeping it. The amendment record discloses it.
    """
    corpus = json.loads((STUDY / "corpus.json").read_text())
    hit = [p for p in corpus["positions"]
           if p["game_id"] == "API-PILOT-v0.1-g2-astra-black" and p["ply"] == 45]
    assert len(hit) == 1
    assert hit[0]["chain_from_ply"] == 43       # the same parent the diagnostic used
    disclosure = (REPO / "docs/reliability-study-v0.1.md").read_text()
    assert "known failure position" in disclosure


def test_the_void_diagnostic_is_labelled_and_excluded():
    void = list(STUDY.glob("VOID_DIAGNOSTIC_DO_NOT_SCORE-*.jsonl"))
    assert len(void) == 1
    assert (STUDY / "VOID_DIAGNOSTIC_DO_NOT_SCORE.sha256").exists()
    assert not (STUDY / "responses-stage1.jsonl").exists(), (
        "a scored response file must not exist under the new execution frame"
    )
