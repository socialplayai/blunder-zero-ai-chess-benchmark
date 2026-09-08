"""Records must be complete enough to reproduce and audit an experiment."""

from __future__ import annotations

import json

import chess.pgn

from bzbench.config import Color, MatchConfig, Protocol
from bzbench.record import GameRecord
from bzbench.referee import Referee
from bzbench.stats import aggregate, format_table, game_summary
from conftest import FirstLegalOpponent, ScriptedAI


def played_game(**kwargs) -> GameRecord:
    base = dict(model_name="gpt-6-astra", protocol=Protocol.RAW,
                ai_color=Color.WHITE, adapter="scripted", stockfish_elo=1600,
                game_id="testgame0001")
    base.update(kwargs)
    config = MatchConfig(**base)
    return Referee(config, ScriptedAI(["e4", "Bc4", "Qh5", "Qxf7#"]),
                   FirstLegalOpponent()).run()


def test_pgn_is_valid_and_carries_the_experiment_headers():
    record = played_game()
    pgn = record.to_pgn()
    game = chess.pgn.read_game(__import__("io").StringIO(pgn))
    assert game is not None
    assert game.headers["Result"] == "1-0"
    assert game.headers["White"] == "gpt-6-astra"
    assert game.headers["Protocol"] == "raw"
    assert game.headers["AIColor"] == "white"
    assert game.headers["StockfishElo"] == "0"  # the fake opponent reports 0
    assert game.headers["Termination"] == "checkmate"
    assert [m.uci() for m in game.mainline_moves()] == record.moves_uci


def test_json_round_trip_preserves_prompts_and_responses(tmp_path):
    record = played_game()
    paths = record.save(tmp_path)
    reloaded = GameRecord.load(paths["json"])
    assert reloaded.result == record.result
    assert reloaded.config == record.config
    assert [t.prompt for t in reloaded.turns] == [t.prompt for t in record.turns]
    assert [t.raw_response for t in reloaded.turns] == [
        t.raw_response for t in record.turns
    ]
    assert reloaded.moves_uci == record.moves_uci


def test_record_stores_reproduction_metadata(tmp_path):
    record = played_game()
    data = json.loads(record.to_json())
    assert data["config"]["protocol"] == "raw"
    assert data["config"]["stockfish_elo"] == 1600
    assert data["config"]["game_id"] == "testgame0001"
    assert data["environment"]["python_chess"]
    assert data["opponent"]["engine_name"]
    assert data["started_at"] and data["finished_at"]
    for turn in data["turns"]:
        assert turn["fen_before"]


def test_saved_files_land_in_a_per_game_directory(tmp_path):
    paths = played_game().save(tmp_path)
    assert paths["dir"].name == "testgame0001"
    assert paths["pgn"].read_text().strip().endswith("1-0")
    assert json.loads(paths["json"].read_text())["result"] == "1-0"


def test_game_summary_reports_the_required_fields():
    summary = game_summary(played_game())
    for key in (
        "win", "draw", "loss", "illegal_moves", "plies", "termination",
        "ai_color", "stockfish_elo", "protocol", "model",
    ):
        assert key in summary
    assert summary["win"] == 1
    assert summary["illegal_moves"] == 0
    assert summary["plies"] == 7


def test_summary_counts_an_illegal_loss():
    config = MatchConfig(model_name="m", adapter="scripted", game_id="g2")
    record = Referee(config, ScriptedAI(["e4", "Qz9"]), FirstLegalOpponent()).run()
    summary = game_summary(record)
    assert summary["loss"] == 1
    assert summary["illegal_moves"] == 1
    assert summary["first_illegal_ply"] == 2
    assert summary["termination"] == "illegal_move"


def test_aggregate_over_several_games():
    rows = [
        game_summary(played_game()),
        game_summary(played_game(game_id="g3", ai_color=Color.BLACK)),
    ]
    agg = aggregate(rows)
    assert agg["games"] == 2
    assert agg["wins"] + agg["draws"] + agg["losses"] == 2
    assert set(agg["protocols"]) == {"raw"}
    assert format_table(rows).splitlines()[0].startswith("game_id")


# ------------------------------------------------- protocol reliability split


def test_summary_separates_malformed_from_state_tracking_failures():
    """Game 2 of the pilot is why these are two different findings."""
    import chess

    from bzbench.config import MatchConfig
    from conftest import ScriptedAI

    # A well formed SAN move that is not legal: the model lost the board.
    config = MatchConfig(model_name="m", adapter="scripted", game_id="statefail")
    referee = Referee(config, ScriptedAI(["Qh5"]), FirstLegalOpponent())
    referee.board = chess.Board("r3r1k1/pp3ppp/8/5N2/Pn6/1N2P3/4KP1P/R1B4q w - - 1 23")
    record = referee.run()
    summary = game_summary(record)
    assert summary["state_tracking_failures"] == 1
    assert summary["malformed_responses"] == 0
    assert summary["legal_responses"] == 0

    # Prose: an output discipline problem, not a board problem.
    record = Referee(
        MatchConfig(model_name="m", adapter="scripted", game_id="malformed"),
        ScriptedAI(["I would play e4 here"]),
        FirstLegalOpponent(),
    ).run()
    summary = game_summary(record)
    assert summary["malformed_responses"] == 1
    assert summary["state_tracking_failures"] == 0


def test_legal_response_rate_counts_responses_not_games():
    clean = game_summary(played_game())
    record = Referee(
        MatchConfig(model_name="m", adapter="scripted", game_id="mixed"),
        ScriptedAI(["e4", "Bc4", "Qa9"]),
        FirstLegalOpponent(),
    ).run()
    rows = [clean, game_summary(record)]
    agg = aggregate(rows)
    assert agg["total_ai_responses"] == clean["ai_responses"] + 3
    assert agg["total_legal_responses"] == clean["legal_responses"] + 2
    assert 0 < agg["legal_response_rate"] < 1
