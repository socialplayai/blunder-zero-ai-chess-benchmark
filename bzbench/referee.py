"""The referee: the only component that sees both sides.

Responsibilities, in order of importance:

1. Enforce the rules. Every AI response is parsed strictly as SAN against the
   current position. An unparseable or illegal move ends the game immediately as
   an AI loss. Nothing is repaired, reinterpreted or retried.
2. Enforce the protocol. The AI is handed a prompt built by `bzbench.protocol`
   from board state only. The referee never passes engine output to the adapter.
3. Record everything: prompts, raw responses, timestamps, configuration, the
   move list, and the reason the game ended.
"""

from __future__ import annotations

import re
import time
from typing import Any, Protocol as TypingProtocol

import chess
import chess.engine

from . import protocol as protocol_mod
from .adapters.base import (
    AbortGame,
    AIPlayer,
    PlayerInfrastructureError,
    ResignGame,
)
from .config import Color, MatchConfig, Protocol
from .record import (
    Actor,
    GameRecord,
    Termination,
    TurnRecord,
    environment_fingerprint,
    utc_now,
)


class Opponent(TypingProtocol):
    """Structural type of a playing opponent. Moves only, never evaluations."""

    def play(self, board: chess.Board) -> chess.Move: ...

    def describe(self) -> Any: ...


def normalize_response(raw: str) -> str:
    """Whitespace trim only.

    This is the complete set of repairs the referee performs on a model
    response. Anything else the model emits (move numbers, prose, several moves,
    a UCI string) is an illegal response and ends the game.
    """
    return raw.strip()


class IllegalMove(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


SAN_PATTERN = re.compile(
    r"^(?:"
    r"O-O-O|O-O"                                   # castling
    r"|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]"            # piece move
    r"|[a-h](?:x[a-h])?[1-8](?:=[QRBN])?"          # pawn move or capture
    r")[+#]?$"
)

_DISAMBIGUATION = re.compile(r"^([KQRBN])[a-h1-8]{0,2}(x?[a-h][1-8].*)$")


def _strip_suffix(san: str) -> str:
    return san.rstrip("+#")


def _drop_disambiguation(san: str) -> str:
    return _DISAMBIGUATION.sub(r"\1\2", san)


def parse_san_strict(board: chess.Board, text: str) -> chess.Move:
    """Parse `text` as a single SAN move legal in `board`, or raise IllegalMove.

    The parsing policy is deliberately strict and fully specified, so that what
    counts as an illegal response is a property of the benchmark and not of a
    library's leniency:

    * the response must be one whitespace-free token matching SAN_PATTERN
      (a UCI string such as `e2e4` is therefore rejected);
    * it must equal the SAN the referee itself generates for a legal move,
      ignoring only the check/checkmate suffix, so `e4` and `e4+` are the same
      claim but `Rd1` does not silently become `Rad1`;
    * an under-specified move that could mean more than one legal move is
      rejected as ambiguous rather than resolved.
    """
    if not text:
        raise IllegalMove("empty response")
    if any(ch.isspace() for ch in text):
        raise IllegalMove("response contains more than one token")
    if not SAN_PATTERN.match(text):
        raise IllegalMove("not valid standard algebraic notation")

    target = _strip_suffix(text)
    exact = [m for m in board.legal_moves if _strip_suffix(board.san(m)) == target]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:  # pragma: no cover - generated SAN is unique by construction
        raise IllegalMove("ambiguous SAN, matches more than one legal move")

    loose = [
        m
        for m in board.legal_moves
        if _drop_disambiguation(_strip_suffix(board.san(m))) == target
    ]
    if len(loose) >= 1:
        raise IllegalMove("ambiguous SAN, matches more than one legal move")
    raise IllegalMove("move is not legal in this position")


_TERMINATION_MAP = {
    chess.Termination.CHECKMATE: Termination.CHECKMATE,
    chess.Termination.STALEMATE: Termination.STALEMATE,
    chess.Termination.INSUFFICIENT_MATERIAL: Termination.INSUFFICIENT_MATERIAL,
    chess.Termination.SEVENTYFIVE_MOVES: Termination.SEVENTYFIVE_MOVES,
    chess.Termination.FIVEFOLD_REPETITION: Termination.FIVEFOLD_REPETITION,
}


class Referee:
    """Runs one benchmark game."""

    def __init__(
        self,
        config: MatchConfig,
        ai_player: AIPlayer,
        opponent: Opponent,
    ) -> None:
        if config.protocol is Protocol.VISUAL:
            raise NotImplementedError(
                "VISUAL protocol is reserved and not implemented yet"
            )
        self.config = config
        self.ai = ai_player
        self.opponent = opponent
        self.board = chess.Board()
        self.history_san: list[str] = []

        opponent_desc = opponent.describe()
        if hasattr(opponent_desc, "to_dict"):
            opponent_desc = opponent_desc.to_dict()
        self.record = GameRecord(
            config=config,
            opponent=dict(opponent_desc),
            adapter=dict(ai_player.describe()),
            environment=environment_fingerprint(),
        )

    # ------------------------------------------------------------------ utils

    @property
    def _ai_to_move(self) -> bool:
        return self.board.turn == (
            chess.WHITE if self.config.ai_color.is_white else chess.BLACK
        )

    def _color_word(self) -> str:
        return "white" if self.board.turn == chess.WHITE else "black"

    def _loss_result(self) -> str:
        """The result string for an AI loss."""
        return "0-1" if self.config.ai_color.is_white else "1-0"

    def _finish(
        self,
        result: str,
        termination: str,
        detail: str = "",
        infrastructure: PlayerInfrastructureError | None = None,
    ) -> GameRecord:
        self.record.result = result
        self.record.termination = termination
        self.record.termination_detail = detail
        self.record.finished_at = utc_now()
        if infrastructure is not None:
            self.record.infrastructure_failure = {
                "kind": infrastructure.kind,
                "message": str(infrastructure),
                "detail": infrastructure.detail,
            }
        summary = self.ai.session_summary()
        if summary is not None:
            self.record.api = summary
        return self.record

    def _push(self, move: chess.Move, turn: TurnRecord) -> None:
        san = self.board.san(move)
        turn.san = san
        turn.uci = move.uci()
        self.board.push(move)
        self.history_san.append(san)
        turn.finished_at = utc_now()
        self.record.turns.append(turn)

    # ------------------------------------------------------------------- play

    def run(self) -> GameRecord:
        while True:
            outcome = self.board.outcome(claim_draw=False)
            if outcome is not None:
                return self._finish(
                    outcome.result(),
                    _TERMINATION_MAP.get(outcome.termination, "other"),
                    detail=outcome.termination.name.lower(),
                )
            if self.board.ply() >= self.config.max_plies:
                return self._finish("*", Termination.MAX_PLIES,
                                    f"reached max_plies={self.config.max_plies}")

            try:
                if self._ai_to_move:
                    finished = self._ai_turn()
                else:
                    finished = self._opponent_turn()
            except AbortGame as exc:
                return self._finish("*", Termination.ABORTED, str(exc))
            except PlayerInfrastructureError as exc:
                # Plumbing, not chess. No result is recorded for either side.
                return self._finish("*", exc.kind, str(exc), infrastructure=exc)
            if finished is not None:
                return finished

    # --------------------------------------------------------------- AI turn

    def _ai_turn(self) -> GameRecord | None:
        prompt, view = protocol_mod.build_prompt(
            self.board,
            self.history_san,
            self.config.protocol,
            self.config.ai_color,
        )
        turn = TurnRecord(
            ply=self.board.ply(),
            actor=Actor.AI,
            color=self._color_word(),
            fen_before=self.board.fen(),
            started_at=utc_now(),
            prompt=prompt,
            view=view.to_dict(),
        )

        started = time.monotonic()
        try:
            raw = self.ai.propose_move(prompt, view)
        except PlayerInfrastructureError:
            turn.finished_at = utc_now()
            turn.response_seconds = time.monotonic() - started
            turn.api = self.ai.pop_turn_metadata()
            turn.rejection_reason = "infrastructure failure, not scored"
            self.record.turns.append(turn)
            raise
        except ResignGame as exc:
            turn.finished_at = utc_now()
            turn.response_seconds = time.monotonic() - started
            turn.raw_response = ":resign"
            turn.legal = None
            self.record.turns.append(turn)
            return self._finish(self._loss_result(), Termination.RESIGNATION, str(exc))
        elapsed = time.monotonic() - started
        turn.api = self.ai.pop_turn_metadata()

        turn.raw_response = raw
        turn.response_seconds = elapsed
        normalized = normalize_response(raw)
        turn.normalized_response = normalized

        budget = self.config.max_move_seconds
        if budget is not None and elapsed > budget:
            turn.legal = None
            turn.rejection_reason = "response time budget exceeded"
            turn.finished_at = utc_now()
            self.record.turns.append(turn)
            return self._finish(
                self._loss_result(),
                Termination.TIME_FORFEIT,
                f"{elapsed:.1f}s exceeded max_move_seconds={budget}",
            )

        try:
            move = parse_san_strict(self.board, normalized)
        except IllegalMove as exc:
            turn.legal = False
            turn.rejection_reason = exc.reason
            turn.finished_at = utc_now()
            self.record.turns.append(turn)
            self.record.illegal_moves.append(
                {
                    "ply": turn.ply,
                    "fen": turn.fen_before,
                    "raw_response": raw,
                    "normalized_response": normalized,
                    "reason": exc.reason,
                }
            )
            return self._finish(
                self._loss_result(),
                Termination.ILLEGAL_MOVE,
                f"ply {turn.ply}: {exc.reason} ({normalized!r})",
            )

        turn.legal = True
        self._push(move, turn)
        return None

    # --------------------------------------------------------- opponent turn

    def _opponent_turn(self) -> GameRecord | None:
        turn = TurnRecord(
            ply=self.board.ply(),
            actor=Actor.OPPONENT,
            color=self._color_word(),
            fen_before=self.board.fen(),
            started_at=utc_now(),
        )
        started = time.monotonic()
        try:
            move = self.opponent.play(self.board)
        except chess.engine.EngineError as exc:
            turn.finished_at = utc_now()
            turn.rejection_reason = str(exc)
            self.record.turns.append(turn)
            return self._finish("*", Termination.ENGINE_ERROR, str(exc))
        turn.response_seconds = time.monotonic() - started
        if move not in self.board.legal_moves:  # pragma: no cover - engine bug
            turn.finished_at = utc_now()
            self.record.turns.append(turn)
            return self._finish(
                "*", Termination.ENGINE_ERROR, f"opponent proposed illegal move {move}"
            )
        self._push(move, turn)
        return None
