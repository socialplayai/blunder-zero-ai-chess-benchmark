"""The study runner must honour the frozen frame and label arms honestly."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import run_reliability_study as runner  # noqa: E402

from fake_openai import FakeClient, FakeResponse  # noqa: E402


def test_arm_labels_separate_native_chain_from_a_switched_current_turn():
    assert runner.arm_label("raw", "fresh", "raw") == "fresh-raw"
    assert runner.arm_label("fen", "fresh", "raw") == "fresh-fen"
    assert runner.arm_label("raw", "chain", "raw") == "native-chain-raw"
    assert runner.arm_label("fen", "chain", "fen") == "native-chain-fen"
    assert runner.arm_label("fen", "chain", "raw") == "switched-current-turn-fen"
    assert runner.arm_label("raw", "chain", "fen") == "switched-current-turn-raw"


def test_the_frozen_constants_match_the_preregistration():
    assert runner.GUARD_USD == 40.0
    assert runner.TRIALS == 2
    assert runner.FUTILITY_MAX_FAILURES == 2


def test_stage_one_is_the_frozen_twenty():
    if not (runner.STUDY_DIR / "corpus.json").exists():
        pytest.skip("corpus not frozen in this checkout")
    stage1 = runner.load_positions(1)
    stage2 = runner.load_positions(2)
    assert len(stage1) == 20 and len(stage2) == 20
    order = json.loads((runner.STUDY_DIR / "stage1-order.json").read_text())
    assert [f"{p['game_id']}#{p['depth']}" for p in stage1] == order["stage1"]
    # No overlap, and every position carries what the chain arms need.
    assert not ({id(p) for p in stage1} & {id(p) for p in stage2})
    for position in stage1 + stage2:
        assert position["response_id"].startswith("resp_")
        assert position["fen"]


def test_every_corpus_position_replays_to_the_recorded_fen():
    """The self check the runner asserts at run time, exercised offline."""
    if not (runner.STUDY_DIR / "corpus.json").exists():
        pytest.skip("corpus not frozen in this checkout")
    from bzbench.record import GameRecord
    from failure_probe import state_at_ply

    cache: dict[str, GameRecord] = {}
    for position in runner.load_positions(1) + runner.load_positions(2):
        path = REPO / position["source_path"]
        record = cache.setdefault(str(path), GameRecord.load(path))
        board, _, _ = state_at_ply(record, position["ply"])
        assert board.fen() == position["fen"], position
        api = next(t.api for t in record.turns
                   if t.ply == position["ply"] and t.actor == "ai")
        assert api["response_id"] == position["response_id"]


def test_chain_arms_branch_and_fresh_arms_do_not(monkeypatch, tmp_path):
    if not (runner.STUDY_DIR / "corpus.json").exists():
        pytest.skip("corpus not frozen in this checkout")
    clients: list[FakeClient] = []
    position = runner.load_positions(1)[0]

    class Recorder(runner.OpenAIResponsesAdapter):
        def __init__(self, **kwargs):
            client = FakeClient([FakeResponse("e4")])
            clients.append(client)
            super().__init__(client=client, **kwargs)

    monkeypatch.setattr(runner, "OpenAIResponsesAdapter", Recorder)
    monkeypatch.setattr(runner, "load_positions", lambda stage: [position])
    monkeypatch.setattr(runner, "STUDY_DIR", tmp_path)

    out = tmp_path / "responses-stage1.jsonl"
    args = runner.build_parser().parse_args(["--stage", "1"])
    runner.run(args)

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 8  # 4 arms x 2 trials for one position
    fresh = [r for r in rows if r["context"] == "fresh"]
    chain = [r for r in rows if r["context"] == "chain"]
    assert len(fresh) == len(chain) == 4
    for client in clients:
        request = client.requests[0]
        assert request["store"] is False
        assert request["tools"] == []
        assert request["max_output_tokens"] == 12000
    assert sum(1 for c in clients if "previous_response_id" in c.requests[0]) == 4
