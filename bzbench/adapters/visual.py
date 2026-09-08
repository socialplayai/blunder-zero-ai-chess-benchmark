"""VISUAL protocol placeholder.

Reserved for a future board-image / computer-use experiment. Model vision is
deliberately not implemented: the interface exists so the rest of the system can
be wired for it, and every entry point fails loudly rather than silently falling
back to a text protocol.
"""

from __future__ import annotations

from ..protocol import TurnView
from .base import AIPlayer


class VisualAdapter(AIPlayer):
    """Not implemented. Present so the interface is fixed, not so it runs."""

    name = "visual"

    def propose_move(self, prompt: str, view: TurnView) -> str:
        raise NotImplementedError(
            "VISUAL protocol is reserved: board-image rendering and model vision "
            "are not implemented yet"
        )

    def render_board_image(self, view: TurnView) -> bytes:
        """Future hook: render the position as a PNG for a vision model."""
        raise NotImplementedError("board image rendering is not implemented yet")
