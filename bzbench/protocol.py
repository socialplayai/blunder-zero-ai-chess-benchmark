"""Protocol layer: builds exactly the information the AI player is allowed to see.

This module is the single choke point for everything that reaches the AI. It
imports `chess` only to read board state; it has no reference to any engine, and
nothing in this file can obtain an evaluation, a best move, a search depth or a
principal variation because none of those values are ever passed into it.

The `TurnView` is built per protocol and structurally omits fields the protocol
forbids: in RAW mode `fen` is None and `legal_moves_san` is None, so a prompt
template cannot render information the protocol does not grant.
"""

from __future__ import annotations

import dataclasses

import chess

from .config import Color, Protocol

# --------------------------------------------------------------------------
# Turn view
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class TurnView:
    """The complete, protocol-filtered information available for one AI turn."""

    protocol: Protocol
    ai_color: Color
    ply: int
    move_number: int
    history_san: tuple[str, ...]
    fen: str | None = None
    legal_moves_san: tuple[str, ...] | None = None

    def to_dict(self) -> dict:
        out = dataclasses.asdict(self)
        out["protocol"] = self.protocol.value
        out["ai_color"] = self.ai_color.value
        out["history_san"] = list(self.history_san)
        if self.legal_moves_san is not None:
            out["legal_moves_san"] = list(self.legal_moves_san)
        return out


def build_turn_view(
    board: chess.Board,
    history_san: list[str],
    protocol: Protocol,
    ai_color: Color,
) -> TurnView:
    """Build the protocol-filtered view of the current position.

    Raises for VISUAL, which is reserved and not implemented.
    """
    if protocol is Protocol.VISUAL:
        raise NotImplementedError(
            "VISUAL protocol is reserved for a future board-image experiment"
        )

    fen: str | None = None
    legal: tuple[str, ...] | None = None

    if protocol in (Protocol.FEN, Protocol.LEGAL):
        fen = board.fen()
    if protocol is Protocol.LEGAL:
        legal = tuple(sorted(board.san(m) for m in board.legal_moves))

    return TurnView(
        protocol=protocol,
        ai_color=ai_color,
        ply=board.ply(),
        move_number=board.fullmove_number,
        history_san=tuple(history_san),
        fen=fen,
        legal_moves_san=legal,
    )


# --------------------------------------------------------------------------
# Prompt rendering
# --------------------------------------------------------------------------

_RESPONSE_RULE = (
    "Respond with exactly one chess move in standard algebraic notation (SAN) "
    "and nothing else. No move number, no punctuation, no explanation, no "
    "commentary. Examples of a well formed response: e4 / Nf3 / exd5 / O-O / "
    "Qxh7# / e8=Q"
)

_INTEGRITY_RULE = (
    "You are playing from your own chess understanding alone. No chess program, "
    "opening reference, endgame reference or analysis tool is available to you, "
    "and no output from any such tool appears below. If a move you give is "
    "illegal in the position, the game is immediately recorded as a loss."
)


def format_history(history_san: tuple[str, ...] | list[str]) -> str:
    """Render the move history as chronological numbered move pairs."""
    if not history_san:
        return "(no moves yet, this is the first move of the game)"
    parts: list[str] = []
    for index, san in enumerate(history_san):
        if index % 2 == 0:
            parts.append(f"{index // 2 + 1}. {san}")
        else:
            parts.append(san)
    return " ".join(parts)


def render_prompt(view: TurnView) -> str:
    """Render the operator-facing prompt for one AI turn.

    The output contains only what `view` carries, and `view` carries only what
    the protocol permits.
    """
    color_word = "White" if view.ai_color.is_white else "Black"
    lines: list[str] = [
        f"You are playing a game of chess as {color_word}.",
        "",
        _INTEGRITY_RULE,
        "",
        "Moves played so far (chronological, standard algebraic notation):",
        format_history(view.history_san),
    ]

    if view.fen is not None:
        lines += ["", "Current position (FEN):", view.fen]

    if view.legal_moves_san is not None:
        lines += [
            "",
            "Legal moves in this position (SAN, alphabetical):",
            " ".join(view.legal_moves_san),
        ]

    lines += [
        "",
        f"It is your move ({color_word}, move {view.move_number}).",
        _RESPONSE_RULE,
    ]
    return "\n".join(lines)


def build_prompt(
    board: chess.Board,
    history_san: list[str],
    protocol: Protocol,
    ai_color: Color,
) -> tuple[str, TurnView]:
    view = build_turn_view(board, history_san, protocol, ai_color)
    return render_prompt(view), view
