# Diagnostic: the API-PILOT-v0.1 game 2 failure position

**Not games. Not Elo evidence. Not scored.** Twenty single position trials
replaying one state, kept out of every games table on purpose.

## The question

In API-PILOT-v0.1 game 2 (RAW, Astra as Black), Astra was winning by more than a
rook and answered `Qh5+` at ply 45. Its queen was on h1 with h2 occupied, so the
move is impossible; 40 legal moves were available. The game ended as a loss under
the frozen rule.

The obvious story was "RAW does not carry enough information to keep the board".
This diagnostic was built to test that story rather than assume it.

## Design

Position `r3r1k1/pp3ppp/8/5N2/Pn6/1N2P3/4KP1P/R1B4q b - - 1 23`, Black to move,
40 legal moves. Four arms, five independent trials each, gpt-6-astra at
reasoning `high`, 12,000 token ceiling, `tools: []`, bare SAN required, prompts
from the frozen builder, verdicts from the frozen SAN validator.

* **fresh**: an independent conversation per trial, `store=false`, no
  `previous_response_id`.
* **chain**: each trial branched independently from the ply 43 stored response,
  which is the conversational state the game was actually in, `store=false` so
  the branch is not itself stored.
* **raw** and **fen** differ by exactly two prompt lines, the FEN header and the
  FEN.

## Result

| Context | RAW | FEN |
| --- | --- | --- |
| Fresh | **5/5 legal** | **5/5 legal** |
| Original chain state | **5/5 legal** | **4/5 legal** |

Nineteen legal responses out of twenty. The single failure was `Qh5+`, the exact
move that ended game 2, and it occurred in the **chain-FEN** arm: the model
produced the impossible move while the authoritative position was in front of it.

Answers given across all arms: `Qd5`, `Qe4`, `Rad8`, and the one `Qh5+`.

## What this does and does not support

**Not supported: "RAW cannot reconstruct this board."** Ten out of ten RAW
trials produced legal, sensible moves from move history alone.

**Not supported: "authoritative board state prevents the impossible move."** The
one reproduction of `Qh5+` happened with the FEN present. Supplying the position
did not prevent it in that trial.

**Not established: any mechanism.** One failure in twenty trials, unevenly
placed, is not enough to assign a cause. The honest reading is that `Qh5+` is an
attractor in this position, that it appears at a low rate under several
conditions, and that neither the protocol nor the conversational state has been
shown to control it. Cause remains `unknown`.

**A caveat specific to the chain-FEN arm.** It is a hybrid: twenty-two turns of
RAW conversation followed by one FEN turn. It answers "would a FEN at that moment
have saved that turn", which is the right counterfactual for the game 2 event. It
is not the same thing as a game played under FEN throughout, and the FEN pair,
which was played under FEN from move one, produced 61 legal responses out of 61.

## Descriptive observations, not findings

Reasoning tokens across five trials per arm: fresh-raw 8,761, fresh-fen 6,632,
chain-raw 3,384, chain-fen 5,150. The fresh arms spent more than the chain arms,
and fresh-raw spent the most. With five trials per cell on one position this is a
small sample efficiency observation and nothing more. It is not evidence that any
protocol systematically costs more reasoning.

Total cost of the twenty trials: $1.62.

## Files

| File | What it is |
| --- | --- |
| `SUMMARY.json` | the 2x2 with per cell counts, tokens, cost and artifact hashes |
| `fresh-arms.json` | every fresh trial: prompt, raw response, verdict, usage, cost, response id |
| `chain-arms.json` | every chain trial, plus the ply 43 response id branched from |
