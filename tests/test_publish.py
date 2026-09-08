"""Published evidence must be closed, sanitised, hashed and immutable."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from publish_game import NotPublishable, publish, sanitise_record, scrub  # noqa: E402

from bzbench.config import Color, MatchConfig, Protocol  # noqa: E402
from bzbench.referee import Referee  # noqa: E402
from conftest import FirstLegalOpponent, ScriptedAI  # noqa: E402


def played(tmp_path, responses=("e4", "Bc4", "Qh5", "Qxf7#"), **kwargs):
    config = MatchConfig(model_name="gpt-6-astra", protocol=Protocol.RAW,
                         ai_color=Color.WHITE, adapter="openai",
                         game_id="pubtest", **kwargs)
    record = Referee(config, ScriptedAI(list(responses)), FirstLegalOpponent()).run()
    return record, record.save(tmp_path / "games")["json"]


def test_publishing_writes_the_four_artifacts_with_matching_hashes(tmp_path):
    _, source = played(tmp_path)
    destination = publish(source, "api-pilot-test", "game-001",
                          results_root=tmp_path / "results", hostname="somehost")
    names = sorted(p.name for p in destination.iterdir())
    assert names == ["MANIFEST.json", "game.json", "game.pgn", "summary.json"]

    manifest = json.loads((destination / "MANIFEST.json").read_text())
    import hashlib

    for name, entry in manifest["artifacts"].items():
        digest = hashlib.sha256((destination / name).read_bytes()).hexdigest()
        assert digest == entry["sha256"], name
        assert entry["bytes"] == (destination / name).stat().st_size


def test_manifest_carries_the_identifiers_needed_to_defend_the_result(tmp_path):
    _, source = played(tmp_path)
    destination = publish(source, "api-pilot-test", "game-001",
                          results_root=tmp_path / "results")
    manifest = json.loads((destination / "MANIFEST.json").read_text())
    assert manifest["experiment"]["protocol"] == "raw"
    assert manifest["experiment"]["prompt_version"] == 2
    assert manifest["experiment"]["ai_color"] == "white"
    assert manifest["outcome"]["result"] == "1-0"
    assert manifest["outcome"]["termination"] == "checkmate"
    assert manifest["outcome"]["illegal_moves"] == 0
    assert manifest["opponent"]["engine_name"]
    assert "benchmark_commit_recorded_in_game" in manifest
    assert "benchmark_commit_at_publish" in manifest
    # The flag describes the tree before publishing, not the files just written.
    assert manifest["working_tree_clean_at_publish"] is (
        __import__("subprocess").run(
            ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip() == ""
    )


def test_published_evidence_is_immutable(tmp_path):
    _, source = played(tmp_path)
    publish(source, "api-pilot-test", "game-001", results_root=tmp_path / "results")
    with pytest.raises(NotPublishable) as exc:
        publish(source, "api-pilot-test", "game-001",
                results_root=tmp_path / "results")
    assert "immutable" in str(exc.value)
    # An explicit override still exists for a mistake caught immediately.
    publish(source, "api-pilot-test", "game-001",
            results_root=tmp_path / "results", force=True)


def test_an_unfinished_game_cannot_be_published(tmp_path):
    record, source = played(tmp_path, responses=("e4", ":abort"))
    assert record.termination == "aborted"
    record.finished_at = None
    path = tmp_path / "unfinished.json"
    path.write_text(record.to_json())
    with pytest.raises(NotPublishable):
        publish(path, "api-pilot-test", "game-002", results_root=tmp_path / "results")


def test_an_aborted_but_closed_game_is_publishable(tmp_path):
    """A non result is still evidence, as long as the record is closed."""
    _, source = played(tmp_path, responses=("e4", ":abort"))
    destination = publish(source, "api-pilot-test", "game-003",
                          results_root=tmp_path / "results")
    manifest = json.loads((destination / "MANIFEST.json").read_text())
    assert manifest["outcome"]["result"] == "*"
    assert manifest["outcome"]["termination"] == "aborted"


def test_the_operator_hostname_is_removed(tmp_path):
    _, source = played(tmp_path)
    pgn = source.with_name("game.pgn")
    pgn.write_text(pgn.read_text().replace('[Site "', '[Site "my-laptop.local'))
    destination = publish(source, "api-pilot-test", "game-004",
                          results_root=tmp_path / "results",
                          hostname="my-laptop.local")
    published = (destination / "game.pgn").read_text()
    assert "my-laptop.local" not in published
    assert "redacted-host" in published
    manifest = json.loads((destination / "MANIFEST.json").read_text())
    assert any("PGN Site header" in entry for entry in manifest["sanitisation"])


def test_key_shaped_strings_are_scrubbed():
    assert scrub("Bearer sk-abcdefghijklmnop") == "Bearer sk-***REDACTED***"
    data, log = sanitise_record({"note": "sk-abcdefghijklmnopqrst"}, None)
    assert data["note"] == "sk-***REDACTED***"
    assert log == ["redacted key shaped strings"]


def test_the_published_record_keeps_every_prompt_and_response(tmp_path):
    record, source = played(tmp_path)
    destination = publish(source, "api-pilot-test", "game-005",
                          results_root=tmp_path / "results", hostname="somehost")
    published = json.loads((destination / "game.json").read_text())
    original = json.loads(source.read_text())
    assert [t["prompt"] for t in published["turns"]] == [
        t["prompt"] for t in original["turns"]
    ]
    assert [t["raw_response"] for t in published["turns"]] == [
        t["raw_response"] for t in original["turns"]
    ]


def test_working_output_stays_untracked():
    """Rules only: a mention inside a comment must not count either way."""
    rules = [
        line.strip()
        for line in (REPO / ".gitignore").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "games/" in rules
    assert "rehearsals/" in rules
    assert not any(rule.startswith("results") for rule in rules)
