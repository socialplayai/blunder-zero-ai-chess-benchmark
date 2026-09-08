# RELIABILITY-STUDY-v0.1: frozen corpus

**Not games. Not Elo evidence.** The corpus is frozen; the study has not run.

`corpus.json` holds the 40 sampled positions, `CORPUS.sha256` its digest.

Frozen **before any Elo 1700 game existed**, from the six games available at the
time, so the reliability corpus cannot depend on how far the strength ladder
happens to climb. Each source is pinned by the sha256 of its published record.

| Source game | Protocol | Elo | Positions |
| --- | --- | --- | --- |
| API-PILOT-v0.1-g1-astra-white | RAW | 1320 | 8 |
| API-PILOT-v0.1-g2-astra-black | RAW | 1320 | 8 |
| API-PILOT-FEN-v0.1-g1-astra-white | FEN | 1320 | 6 |
| API-PILOT-FEN-v0.1-g2-astra-black | FEN | 1320 | 6 |
| API-PILOT-FEN-v0.2-g1-astra-white | FEN | 1500 | 6 |
| API-PILOT-FEN-v0.2-g2-astra-black | FEN | 1500 | 6 |

Frame achieved exactly: 16 RAW source and 24 FEN source; depth strata 13 early,
13 middle, 14 late, no shortfall; 20 positions with White to move and 20 with
Black; minimum separation 3 accumulated turns in every game except
API-PILOT-v0.1 game 2, which is too short for its quota of 8 and runs at
separation 2 exactly as preregistered.

Selection used **no engine information**: no evaluation, accuracy, or judgement
value entered the sampler, which is asserted by the tests.

## What the corpus is not

It is not a hard corpus. Across the 40 positions there is **1** position with the
side to move in check, **15** with castling rights still available, and **0** with
a promotion or an en passant capture available. That is what naturalistic
sampling from six real games produced, and it is deliberately not fixed by
substituting harder boards, which would change the estimand from ordinary play to
a stress test.

The consequence is preregistered rather than discovered later: this corpus
**cannot say anything** about legality when a promotion or an en passant capture
is on the board. Those belong to the separate stress benchmark, which does not
exist yet.

Legal move counts range from 6 to 60, median 42; depths range from 5 to 47
accumulated model turns.

## Next

Build the batch runner and the analysis pass, then execute under the frozen
frame: 4 arms x 2 trials x 40 positions, Stage 1 futility check after the first
20 positions, $40 study guard. Nothing runs while a scored game is running.
