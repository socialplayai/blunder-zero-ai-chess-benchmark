"""The manual (copy/paste) adapter."""

from __future__ import annotations

import io

import chess
import pytest

from bzbench import adapters
from bzbench.adapters.base import AbortGame, ResignGame
from bzbench.adapters.manual import ManualAdapter
from bzbench.adapters.visual import VisualAdapter
from bzbench.config import Color, Protocol
from bzbench.protocol import build_prompt


def view_and_prompt():
    return build_prompt(chess.Board(), [], Protocol.RAW, Color.WHITE)


def test_prompt_is_printed_for_the_operator_to_copy():
    prompt, view = view_and_prompt()
    out = io.StringIO()
    adapter = ManualAdapter(input_fn=lambda: "e4\n", out=out)
    assert adapter.propose_move(prompt, view) == "e4\n"
    printed = out.getvalue()
    assert prompt in printed
    assert "COPY THE BLOCK BELOW INTO THE MODEL" in printed
    assert "Paste the model response" in printed


def test_response_is_returned_verbatim():
    prompt, view = view_and_prompt()
    adapter = ManualAdapter(input_fn=lambda: "  Nf3  \n", out=io.StringIO())
    assert adapter.propose_move(prompt, view) == "  Nf3  \n"


def test_resign_and_abort_tokens():
    prompt, view = view_and_prompt()
    with pytest.raises(ResignGame):
        ManualAdapter(input_fn=lambda: ":resign", out=io.StringIO()).propose_move(
            prompt, view
        )
    with pytest.raises(AbortGame):
        ManualAdapter(input_fn=lambda: ":abort", out=io.StringIO()).propose_move(
            prompt, view
        )


def test_closed_input_stream_aborts_rather_than_inventing_a_move():
    prompt, view = view_and_prompt()

    def eof() -> str:
        raise EOFError

    with pytest.raises(AbortGame):
        ManualAdapter(input_fn=eof, out=io.StringIO()).propose_move(prompt, view)


def test_registry_lists_the_known_adapters():
    assert {"manual", "visual", "openai"} <= set(adapters.available())
    assert isinstance(adapters.create("manual"), ManualAdapter)
    with pytest.raises(ValueError):
        adapters.create("anthropic")


def test_visual_adapter_refuses_to_run():
    prompt, view = view_and_prompt()
    with pytest.raises(NotImplementedError):
        VisualAdapter().propose_move(prompt, view)
    with pytest.raises(NotImplementedError):
        VisualAdapter().render_board_image(view)


def test_registering_a_future_adapter():
    class Dummy(ManualAdapter):
        name = "dummy"

    adapters.register("dummy-test", Dummy)
    assert "dummy-test" in adapters.available()
    with pytest.raises(ValueError):
        adapters.register("dummy-test", Dummy)
