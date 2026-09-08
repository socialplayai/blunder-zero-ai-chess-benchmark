# RELIABILITY-STUDY-v0.1: Stage 1 results

**RELIABILITY STUDY COMPLETE: FUTILITY STOP**

Not games. Not Elo evidence. Not scored chess. A preregistered reliability study
of response legality, executed once, stopped by its own rule.

## Outcome

Across 160 preregistered responses spanning fresh and chained RAW and FEN
conditions, GPT-6 Astra produced **159 legal, well formed chess moves. One
illegal move occurred.**

The preregistered futility rule specified that 0 to 2 illegal responses across
Stage 1 would stop the study **without a comparative conclusion between
conditions**. That rule fired. Therefore:

* **Stage 2 was not run.**
* **No arm is claimed to be more or less reliable than another.**
* Arm level counts below are **descriptive only**.
* The study outcome is that illegal move events were **too rare for this
  instrument and sample size to discriminate between the tested conditions**.

This is not a failed experiment. The endpoint was measured and found too sparse
to support the comparison the design was built to make, which is itself the
finding.

## Arm counts, descriptive and non comparative

Reported because the preregistration requires them, not because they support a
ranking. **Do not rank these arms. Do not compute relative risk from one event.**

| Arm | Legal | Illegal | Malformed | n |
| --- | --- | --- | --- | --- |
| `fresh-raw` | 40 | 0 | 0 | 40 |
| `fresh-fen` | 40 | 0 | 0 | 40 |
| `native-chain-raw` | 15 | 1 | 0 | 16 |
| `native-chain-fen` | 24 | 0 | 0 | 24 |
| `switched-current-turn-raw` | 24 | 0 | 0 | 24 |
| `switched-current-turn-fen` | 16 | 0 | 0 | 16 |

The four arm names distinguish what each cell actually is. `native-chain-*` is a
chained trial whose protocol matches its source game. `switched-current-turn-*`
changes only the current turn's representation on top of a history built under
the other protocol. The uneven n per arm follows from the corpus being 16 RAW
source and 24 FEN source positions, which was fixed before execution.

## The single illegal response, in full

| Field | Value |
| --- | --- |
| Position key | `API-PILOT-v0.1-g2-astra-black#22` |
| Source game | `API-PILOT-v0.1-g2-astra-black` (raw protocol, Elo 1320) |
| Ply | 45 |
| Chain depth | 22 accumulated model turns (late) |
| Arm | `native-chain-raw` |
| Trial | 2 |
| Side to move | black |
| Raw response | `Qh5+` |
| Category | `illegal_move_response` |
| Reason | move is not legal in this position |
| Response id | `resp_048ede5d002e3695016a9fdd4817d487d194e9f3badffc2ace` |
| Branched from | `resp_048ede5d002e3695006a9fa48a809887d1b272252c8a60ee89` |

Board: `r3r1k1/pp3ppp/8/5N2/Pn6/1N2P3/4KP1P/R1B4q b - - 1 23`

**Why the move is illegal.** Black's only queen is on h1. The h file is blocked
by a white pawn on h2, so `h1h5` is not even pseudo legal. Forty legal moves were
available, including `Qxh2`, `Rxe3+` and `Qd1+`. The response also claims a check
that no legal move in the position delivers.

**Original occurrence.** The sole Stage 1 illegal response occurred at the same
sampled position and reproduced the same impossible move, `Qh5+`, that had
terminated the original RAW game (API-PILOT-v0.1 game 2, ply 45, a loss under the
frozen illegal move rule while Astra was ahead by more than a rook).

**The earlier diagnostic reproduced the same move in a different arm.** The ply
45 probe published at `results/diagnostics/api-pilot-v0.1-g2-ply45/` ran 20
trials on this exact board and produced `Qh5+` once, in the **chain FEN** arm.
Stage 1 produced it once, in the **native chain RAW** arm.

**What may and may not be inferred.** The same impossible move has now appeared
twice on this board, in two different arms, across two experiments. The correct
reading is that **this position appears unusually failure prone, or carries a
response attractor**. The data do not identify a mechanism. Specifically, it is
**not** supported that native chain RAW causes the failure, that RAW causes it,
that chaining causes it, that FEN prevents it, or that any arm is superior.

**Disclosed in advance.** That this position was in the corpus was recorded
before execution, in `docs/reliability-study-v0.1.md`, precisely so that a
failure here would be read as the least surprising failure available rather than
as an independent discovery.

## Futility rule evaluation

| | |
| --- | --- |
| Rule, frozen before execution | 0 to 2 illegal responses in Stage 1: stop, report arm counts, make no comparative conclusion. 3 or more: Stage 2 authorised. |
| Observed | **1** |
| Verdict | **Futility stop.** Stage 2 not run. |
| Decided by | The runner, automatically, from the frozen threshold. Not by operator judgement after seeing the data. |

## Operational totals

| | |
| --- | --- |
| Responses (scored) | 160 |
| Legal | 159 |
| Illegal | 1 |
| Malformed | 0 |
| Positions | 20 of the frozen 40 (Stage 1 half) |
| Input tokens | 1,002,332 |
| Output tokens | 216,843 |
| Reasoning tokens | 215,523 |
| Study cost | $15.7762 of the $40 guard |
| Elapsed | 113.7 minutes |
| Infrastructure incidents | 0 |
| Execution commit | `be8ec7b08a78d1aad6393373d4eabb9b0f8579a3` |
| Corpus sha256 | `386416d2d94201099d8ecc40eed1e9e2e79b65bbc913ec5f4fed334f950432ab` |
| Corpus seed | 20260908 |
| Ordering seed | 20260908 |

### Amendment history

| Id | What |
| --- | --- |
| C1 | Defined which 20 of the frozen 40 form Stage 1 and the execution order, before any response existed. The corpus stores positions sorted by (game_id, depth), so a naive first 20 would have been 20 FEN source positions from four of six games. |
| C2 | Chain arms branch from the **preceding** model turn, not the sampled turn's own response. Applied after 8 of 160 responses, before any scored response existed. |

### Void pre-C2 spend, excluded from every figure above

Before C2, 8 responses were generated against the defective frame: 4 chain
responses whose context already contained the answer being asked for, and 4
fresh responses that were technically valid and **deliberately discarded** so
the study has one clean execution frame. Diagnostic spend **$0.98**, separate
from the $15.78 scored above.

Retained for audit only as
`VOID_DIAGNOSTIC_DO_NOT_SCORE-responses-stage1.jsonl`,
sha256 `a5717651c4bedc17e5bf48b1cb0f8771d6ea1c058cf424a0bb04d6989daeefe7`. It has never entered a scored denominator.

## Study conclusion

The preregistered illegal move endpoint was too sparse to discriminate the four
reliability conditions at this sample size. This suggests that simple move
legality failure has become a weak instrument for studying GPT-6 Astra
reliability under the tested chess conditions. Detecting smaller differences
would require substantially more samples or a separately preregistered harder
stress benchmark.

**Scope.** This statement applies **only** to the tested positions, protocols and
sample. It does not generalise from chess legality to general AI reliability, and
it does not claim that illegal moves are universally rare for this model.

## Programme context

Reported separately, with denominators kept apart on purpose.

**Track 1, strength.** Astra beat strength limited Stockfish 18 at Elo 1320 and
1500 in both colours and lost both games at 1700. That is a **ladder bracket, not
an Elo rating**. FEN supplied the authoritative current position every turn.

**Track 2, reliability.** 159 of 160 legal, well formed responses. Futility stop.
No condition comparison.

**The two denominators are not merged.** Track 1 counts responses inside scored
games under one protocol per game. Track 2 counts single position trials across
four conditions. A combined percentage would describe no population that exists.

## Files

| File | What |
| --- | --- |
| `responses-stage1.jsonl` | every scored response: prompt context, raw reply, verdict, usage, cost, response ids |
| `corpus.json` | the 40 frozen positions, C1 and C2 applied |
| `stage1-order.json` | which 20 form Stage 1, and the execution order |
| `CORPUS.sha256` | corpus digest |
| `VOID_DIAGNOSTIC_DO_NOT_SCORE-*.jsonl` | the 8 pre C2 responses, never scored |
| `MANIFEST.json` | hashes of everything above |
