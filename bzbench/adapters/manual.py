"""Manual adapter: a human operator relays prompts to a model and back.

The operator copies the printed prompt into the model under test (for the first
experiment: Codex with GPT-6 Astra) and pastes the model's reply back. The reply
is recorded verbatim and handed to the referee without repair.
"""

from __future__ import annotations

import sys
from typing import Callable, TextIO

from ..protocol import TurnView
from .base import AbortGame, AIPlayer, ResignGame

RULE = "=" * 72

ABORT_TOKENS = {":abort", ":quit", ":exit"}
RESIGN_TOKENS = {":resign"}


class ManualAdapter(AIPlayer):
    """Print the prompt, read one line of model output from the operator."""

    name = "manual"

    def __init__(
        self,
        *,
        input_fn: Callable[[], str] | None = None,
        out: TextIO | None = None,
    ) -> None:
        self._out = out if out is not None else sys.stdout
        self._input_fn = input_fn if input_fn is not None else self._default_input

    def _default_input(self) -> str:
        line = sys.stdin.readline()
        if line == "":
            raise EOFError
        return line

    def _write(self, text: str = "") -> None:
        self._out.write(text + "\n")
        self._out.flush()

    def propose_move(self, prompt: str, view: TurnView) -> str:
        self._write()
        self._write(RULE)
        self._write(f"COPY THE BLOCK BELOW INTO THE MODEL  (ply {view.ply}, "
                    f"protocol {view.protocol.value})")
        self._write(RULE)
        self._write(prompt)
        self._write(RULE)
        self._write("Paste the model response (one SAN move), "
                    "or :resign / :abort:")
        self._out.flush()

        try:
            raw = self._input_fn()
        except EOFError as exc:
            raise AbortGame("input stream closed") from exc

        token = raw.strip().lower()
        if token in ABORT_TOKENS:
            raise AbortGame("operator aborted the session")
        if token in RESIGN_TOKENS:
            raise ResignGame("AI player resigned")
        return raw
