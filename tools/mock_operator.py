"""Mock operator: drives a real `bzbench play` session end to end.

This is a rehearsal harness, not part of the benchmark. It plays the role of
both the human operator and the model:

    prompt on stdout  ->  parsed  ->  a move  ->  written to stdin

The mock model is deliberately weak and deliberately blind: it reconstructs the
position from the prompt text alone, exactly as a model reading the prompt
would have to, and then picks a legal move at random with a fixed seed. If the
prompt ever stopped carrying enough information to play, this harness would
fail, which makes it a live check on the RAW protocol as well as on the CLI.

    python3 tools/mock_operator.py --protocol raw --elo 1350 --seed 7

Never use this for a real benchmark run: the record it produces describes a
random mover, not a model.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import re
import subprocess
import sys

import chess

REPO = pathlib.Path(__file__).resolve().parents[1]
RULE = "=" * 72
PROMPT_END = "Paste the model response"

MOVE_TOKEN = re.compile(r"\d+\.\s*|\s+")


def parse_history(prompt: str) -> list[str]:
    """Recover the move history from the prompt the operator was shown."""
    lines = prompt.splitlines()
    try:
        index = lines.index(
            "Moves played so far (chronological, standard algebraic notation):"
        )
    except ValueError:  # pragma: no cover - prompt format changed
        raise SystemExit("could not find the move history in the prompt")
    line = lines[index + 1].strip()
    if line.startswith("(no moves yet"):
        return []
    return [tok for tok in MOVE_TOKEN.split(line) if tok]


def board_from_prompt(prompt: str) -> chess.Board:
    fen_match = re.search(r"^Current position \(FEN\):\n(.+)$", prompt, re.M)
    if fen_match:
        return chess.Board(fen_match.group(1).strip())
    board = chess.Board()
    for san in parse_history(prompt):
        board.push_san(san)
    return board


def choose_move(board: chess.Board, rng: random.Random, illegal_rate: float) -> str:
    if rng.random() < illegal_rate:
        return "Qz9"  # a deliberate protocol violation, to exercise the referee
    move = rng.choice(sorted(board.legal_moves, key=lambda m: m.uci()))
    return board.san(move)


def run(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    command = [
        sys.executable, "-u", "-m", "bzbench.cli", "play",
        "--model", args.model,
        "--protocol", args.protocol,
        "--color", args.color,
        "--adapter", "manual",
        "--elo", str(args.elo),
        "--stockfish", args.stockfish,
        "--nodes", str(args.nodes),
        "--max-plies", str(args.max_plies),
        "--out", args.out,
        "--notes", "mock operator rehearsal, the player is a random mover",
    ]
    if args.game_id:
        command += ["--game-id", args.game_id]
    if args.analyze:
        command += ["--analyze", "--depth", str(args.depth)]

    process = subprocess.Popen(
        command, cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=None, text=True, bufsize=1,
    )
    assert process.stdin and process.stdout

    buffer: list[str] = []
    moves_played = 0
    while True:
        line = process.stdout.readline()
        if line == "":
            break
        sys.stdout.write(line)
        buffer.append(line.rstrip("\n"))
        if line.startswith(PROMPT_END):
            prompt = extract_prompt(buffer)
            board = board_from_prompt(prompt)
            san = choose_move(board, rng, args.illegal_rate)
            moves_played += 1
            sys.stdout.write(f"[mock model] {san}\n")
            process.stdin.write(san + "\n")
            process.stdin.flush()
            buffer.clear()

    process.stdin.close()
    code = process.wait()
    print(f"\n[mock operator] {moves_played} model responses, exit code {code}")
    return code


def extract_prompt(buffer: list[str]) -> str:
    """The prompt is the block between the second and third rule lines."""
    rules = [i for i, line in enumerate(buffer) if line == RULE]
    if len(rules) < 3:  # pragma: no cover - prompt format changed
        raise SystemExit("could not locate the prompt block")
    return "\n".join(buffer[rules[1] + 1: rules[2]])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--protocol", default="raw",
                        choices=["raw", "fen", "legal"])
    parser.add_argument("--color", default="white", choices=["white", "black"])
    parser.add_argument("--model", default="mock-random-mover")
    parser.add_argument("--elo", type=int, default=1350)
    parser.add_argument("--nodes", type=int, default=2000)
    parser.add_argument("--stockfish", default="stockfish")
    parser.add_argument("--max-plies", type=int, default=200)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--illegal-rate", type=float, default=0.0,
                        help="probability of sending a deliberately illegal move")
    parser.add_argument("--game-id", default=None)
    parser.add_argument("--out", default="games")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--depth", type=int, default=12)
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
