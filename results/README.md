# Published results

Working experiment output is not published evidence.

* `games/` is untracked. It holds whatever an operator produced: rehearsals,
  interrupted runs, probes, mistakes. Nothing in it is a claim.
* `rehearsals/` is untracked. Mock operator output only.
* `results/<pilot>/<slot>/` is tracked, is written once, and holds a closed
  game that is being asserted publicly.

A slot is created by `tools/publish_game.py`, which refuses to publish an
unfinished record and refuses to overwrite an existing slot. Each slot contains:

| File | What it is |
| --- | --- |
| `game.pgn` | the game, with the operator's hostname removed |
| `game.json` | the full record: every prompt sent, every raw response received, per move API usage and cost, the analysis pass |
| `summary.json` | the one row version used in reports |
| `MANIFEST.json` | commit identifiers, experiment configuration, outcome, usage totals, pricing provenance, what was redacted, and a sha256 of each of the three files above |

The point of keeping `game.json` complete is that the integrity claims can be
rechecked against the record instead of trusted. Every prompt is there, so
anyone can verify that a RAW game contained no FEN and no legal move list, and
every raw response is there, so the legality judgements can be recomputed.

## Reproducing a published game

The opponent is reproducible: check out the commit named in the manifest and
replay the same command with the same fixed node count against the same
Stockfish build. The model is not reproducible in the same sense, which is why
the raw responses are stored rather than only the moves.

## Index

Scored games only. Diagnostics live under `results/diagnostics/` and are never
mixed into this table.

| Slot | Game | Astra | Opponent | Result | Illegal | Accuracy | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `api-pilot-v0.1/game-001` | API-PILOT-v0.1 game 1 | White | Stockfish 18, Elo 1320, 200k nodes | 1-0 win, checkmate | 0 | 90.91% | $1.25 |
| `api-pilot-v0.1/game-002` | API-PILOT-v0.1 game 2 | Black | Stockfish 18, Elo 1320, 200k nodes | 1-0 loss, illegal move | 1 | 94.07% | $0.63 |

Game 2 is the paired colour of game 1 and the more informative of the two: Astra
was winning by more than a rook when it answered `Qh5+` with its queen on h1 and
the h2 square occupied, which is not a legal move. The record contains the
position, the legal move list at that moment and the raw response, so the
judgement can be rechecked rather than believed.

The headline of the pair is not "one win, one loss". It is that **Astra played
strong chess and failed the RAW interface on board state legality**. Those are
separate findings and are reported separately, see
[docs/reporting-dimensions.md](../docs/reporting-dimensions.md).

Game 2 ran at a commit other than the preregistered one. It is kept, not
re-run, and the difference is documented in
[api-pilot-v0.1/DEVIATIONS.md](api-pilot-v0.1/DEVIATIONS.md).

| `api-pilot-fen-v0.1/game-001` | API-PILOT-FEN-v0.1 game 1 | White | Stockfish 18, Elo 1320, 200k nodes | 1-0 win, checkmate | 0 | 96.50% | $1.14 |
| `api-pilot-fen-v0.1/game-002` | API-PILOT-FEN-v0.1 game 2 | Black | Stockfish 18, Elo 1320, 200k nodes | 0-1 win, checkmate | 0 | 98.12% | $1.07 |

| `api-pilot-fen-v0.2/game-001` | API-PILOT-FEN-v0.2 game 1 | White | Stockfish 18, Elo 1500, 200k nodes | 1-0 win, checkmate | 0 | 91.67% | $2.11 |
| `api-pilot-fen-v0.2/game-002` | API-PILOT-FEN-v0.2 game 2 | Black | Stockfish 18, Elo 1500, 200k nodes | 0-1 win, checkmate | 0 | 93.84% | $11.50 |

The 1320 FEN pair ran at the preregistered commit with no deviations, see
[api-pilot-fen-v0.1/DEVIATIONS.md](api-pilot-fen-v0.1/DEVIATIONS.md). Causal
attribution for the RAW game 2 failure is not settled by this pair, see
[diagnostics/api-pilot-v0.1-g2-ply45/](diagnostics/api-pilot-v0.1-g2-ply45/).
