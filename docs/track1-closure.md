# Track 1 closed: STRENGTH BRACKET COMPLETE

Frozen at commit `c62f82f`. Six scored FEN games across three rungs. **No further
games will be added to this bracket.**

## The result, in the only wording that is defensible

> **With the current position supplied as FEN every turn, GPT-6 Astra beat
> strength limited Stockfish 18 at Elo 1320 and 1500 in both colours, then lost
> at 1700 in both colours. This brackets its playing strength between the 1500
> and 1700 rungs of this test, on two games per rung.**

Every game was played with no chess engine, no opening book, no tablebase, no
tools of any kind available to the model, against Stockfish 18 limited by
`UCI_LimitStrength` at a fixed 200,000 node budget.

## What the six games show

| Question | Result |
| --- | --- |
| Can Astra obey the chess interface reliably? | Yes. **329 legal responses out of 329.** |
| Can Astra play non trivial chess? | Yes. Beat Stockfish 18 at 1320 and 1500, both colours. |
| Where does it stop winning? | First observed losses at 1700, both colours. |

And one observation that is a sanity check rather than a finding:

| Rung | White ACPL | Black ACPL | Results |
| --- | --- | --- | --- |
| 1320 | 13.4 | 11.0 | win, win |
| 1500 | 35.0 | 30.4 | win, win |
| 1700 | 56.7 | 32.1 | loss, loss |

Move quality degraded monotonically as the opponent strengthened, and the
opponent outscored Astra on ACPL for the first time at 1700. That is the shape a
genuine chess playing system produces against progressively stronger opposition.
It is not a rating.

## The most interesting single game

API-PILOT-FEN-v0.3 game 2: **175 plies, 87 Astra responses, zero illegal and
zero malformed, 2 mistakes and 2 blunders**, lost in a long rook endgame. That
reads as a chess player being outplayed, not as a language model breaking down.

## Wording rules for anything published

**Say:**

* "With the current position supplied as FEN, Astra played a 175 ply game
  against Stockfish 1700 without producing a single illegal move."
* "329 consecutive legal responses across the FEN programme, no malformed
  output."
* "Strength brackets between the 1500 and 1700 rungs of this test."
* Always name the **FEN protocol** prominently.

**Do not say:**

* "Astra has a 1600 Elo." Six games do not produce a rating, and these rungs are
  a strength limited engine, not a rating pool.
* "Astra can remember a chessboard for 175 moves." **FEN supplied the board every
  turn.** These games test chess reasoning and move selection, not long horizon
  board reconstruction. Conflating the two would be the single most misleading
  claim available from this data.
* Anything about RAW reliability derived from FEN games. RAW is a separate
  question and has one observed failure in 54 responses.

## Why the bracket is not being narrowed

Two more games at 1700, or a 1600 rung, would turn "between 1500 and 1700" into
"around 1600". Useful eventually, not transformative. The reliability question is
unanswered and orthogonal, so the next spend goes to Track 2. The six games are
frozen and will still be here when a larger rating study is worth running.

## Artifacts

`results/api-pilot-v0.1/`, `results/api-pilot-fen-v0.1/`,
`results/api-pilot-fen-v0.2/`, `results/api-pilot-fen-v0.3/`. Each slot holds the
PGN, the complete record with every prompt and raw response, the summary and a
manifest with commit ids and artifact hashes. Total programme spend to this
point: $36.94.
