"""Preflight must verify a real run without starting one."""

from __future__ import annotations

import pathlib

import pytest

from bzbench import cli
from fake_openai import FakeClient, FakeResponse, FakeUsage


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient([FakeResponse("x", usage=FakeUsage(10, 0, 5, 4))])
    monkeypatch.setattr(cli, "build_client", lambda *a, **k: client)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-preflight-0000000000")
    return client


def run(tmp_path, stockfish_path, *extra):
    return cli.main([
        "preflight", "--adapter", "openai", "--stockfish", stockfish_path,
        "--out", str(tmp_path), "--nodes", "1000", *extra,
    ])


@pytest.mark.slow
def test_preflight_passes_and_does_not_play(tmp_path, stockfish_path, fake_client,
                                            capsys):
    assert run(tmp_path, stockfish_path) == 0
    out = capsys.readouterr().out
    for line in (
        "benchmark configuration", "output directory writable", "stockfish available",
        "pricing metadata", "reasoning effort allowed", "API key in environment",
        "model accessible", "request exposes no tools",
    ):
        assert line in out
    assert "PASSED" in out
    assert list(pathlib.Path(tmp_path).glob("**/game.json")) == []
    assert list(pathlib.Path(tmp_path).glob("**/game.pgn")) == []


@pytest.mark.slow
def test_preflight_probe_is_tiny_and_toolless(tmp_path, stockfish_path, fake_client):
    assert run(tmp_path, stockfish_path, "--probe-max-output-tokens", "16") == 0
    assert fake_client.calls == 1
    request = fake_client.requests[0]
    assert request["max_output_tokens"] == 16
    assert request["tools"] == []
    assert "previous_response_id" not in request
    assert request["reasoning"] == {"effort": "high"}
    assert len(request["input"]) < 200  # not a chess position


@pytest.mark.slow
def test_preflight_with_no_probe_sends_nothing(tmp_path, stockfish_path, fake_client):
    assert run(tmp_path, stockfish_path, "--no-probe") == 0
    assert fake_client.calls == 0


@pytest.mark.slow
def test_preflight_fails_without_an_api_key(tmp_path, stockfish_path, monkeypatch,
                                            capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert run(tmp_path, stockfish_path) == 1
    out = capsys.readouterr().out
    assert "[FAIL] API key in environment" in out
    assert "FAILED" in out


@pytest.mark.slow
def test_preflight_rejects_an_unsupported_reasoning_level(tmp_path, stockfish_path,
                                                          fake_client, capsys):
    assert run(tmp_path, stockfish_path, "--reasoning-effort", "none") == 1
    out = capsys.readouterr().out
    assert "[FAIL] reasoning effort allowed" in out
    assert fake_client.calls == 0


@pytest.mark.slow
def test_preflight_reports_the_cost_estimate_and_the_guard(tmp_path, stockfish_path,
                                                            fake_client, capsys):
    assert run(tmp_path, stockfish_path, "--estimate-moves", "60",
               "--estimate-output-tokens", "6000") == 0
    out = capsys.readouterr().out
    assert "Upper bound cost estimate" in out
    assert "spend guard" in out
    assert "pricing_verified_at" in out


def test_preflight_never_prints_the_key(tmp_path, stockfish_path, fake_client, capsys):
    import shutil

    if shutil.which("stockfish") is None:
        pytest.skip("stockfish not available")
    run(tmp_path, stockfish_path)
    captured = capsys.readouterr()
    assert "sk-test-preflight-0000000000" not in captured.out
    assert "sk-test-preflight-0000000000" not in captured.err
