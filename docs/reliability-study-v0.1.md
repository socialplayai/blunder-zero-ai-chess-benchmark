# RELIABILITY-STUDY-v0.1 (design, revised, not yet authorised to execute)

Track 2, reliability science. Entirely non Elo. No game is played, no result is
produced, nothing here enters a strength table.

Revision 2: **more distinct boards, fewer repeats per board**, because the ply 45
diagnostic already showed the failure may be highly position specific, and 20
answers from one board are one board.

Revision 3: balance **games first, protocols second**, and stop pretending the
2x2 is cleaner than it is. A chained trial inherits the protocol history of the
game it came from, so the four chained cells are not one thing. See the
vocabulary section.

## The question

> Does accumulated conversation length, or the supply of authoritative board
> state, materially affect response legality during **realistic** chess play?

The estimand is ordinary play. That is why the corpus is naturalistic and is not
enriched with hard positions, which would silently change the question to "what
happens under a chess state stress test". A stress benchmark is a separate,
later, separately labelled experiment.

## Design

**Unit of analysis: one response**, clustered by position and by source game.

| | |
| --- | --- |
| Positions | **40 distinct**, naturalistic, preregistered before any call |
| Arms | fresh RAW, chain RAW, fresh FEN, chain FEN |
| Trials per arm per position | **2** |
| Total responses | **320** |
| Nominal spend at $0.081 per response | **$25.92** |
| Stage 1 spend | **$12.96** |
| Study guard | **$40**, checked before every request |
| Extension beyond 320 responses | requires a new ruling |

Held at the frozen values: gpt-6-astra, reasoning `high`, 12,000 token ceiling,
`tools: []`, bare SAN required, prompts from the frozen builder, verdicts from
the frozen validator, `store=false` on every trial. **No legal move list appears
in any prompt**; the validator computes legality after the response.

## Preregistered two stage stopping rule

Information based, not significance based. Frozen before execution.

**Stage 1: the first 20 positions, 160 responses.**

* **0 to 2 illegal responses in total:** stop. Report the arm counts and state
  that the event is too rare to estimate arm differences with this design. No
  comparative conclusion. Spend ends at about $13.
* **3 or more:** continue automatically to all 40 positions.
* **Any guard hit:** stop under the frozen guard policy.

The rule triggers on total failure count, never on whether a comparison looks
significant.

## Corpus construction

Sampled from completed, published games at the moment of freezing, using each
position's real stored response for the chain arms.

**Chain depth strata, frozen before sampling**, counted as Astra turns already
accumulated in that game's conversation before the sampled turn:

| Stratum | Accumulated turns | Positions |
| --- | --- | --- |
| early | 5 to 10 | 13 |
| middle | 11 to 20 | 13 |
| late | 21 or more | 14 |

The hypothesis is about accumulated conversation length, so depth is stratified
explicitly rather than left to whatever the sample happens to contain.

**Per game quotas, frozen. Games are balanced first, protocols second.**

| Source | Games | Positions each | Total |
| --- | --- | --- | --- |
| RAW games | 2 | 8 | 16 |
| FEN games | 4 | 6 | 24 |

16/24 is an experimental sampling decision, not a prevalence weighting. Equal
protocol totals would have meant taking 10 positions from each of only two RAW
games, which makes the dependence problem worse in exchange for a symmetry that
does not buy anything.

**Also balanced, and recorded per position:**

* side to move, roughly balanced;
* board features present naturally, never constructed: in check, castling rights
  still available, a promotion available, an en passant capture available. These
  are recorded as covariates. They are **not** used to select harder positions.

**Separation rule.** Within a source game, sampled positions are at least **3
accumulated Astra turns** apart, so the study does not spend eight samples on
nearly identical nested prefixes. Where a game is too short for its quota at
separation 3, the separation is relaxed to 2, then to 1, only as far as needed,
and the relaxation is recorded per game in the corpus file.

This bites immediately, and is preregistered rather than discovered later:
API-PILOT-v0.1 game 2 has 23 model turns, which allows at most 6 positions at
separation 3 and 9 at separation 2. **Its quota of 8 therefore runs at
separation 2**, and that is recorded in the corpus file. The other five games
meet their quotas at separation 3.

**Depth coverage.** The global quotas of 13 early, 13 middle and 14 late are
frozen, and every source game contributes across the depth bins it actually
contains rather than the bins being satisfied by one or two long games. Where
the per game quotas and the global depth quotas cannot both be met exactly, the
per game quotas win and the depth shortfall is recorded. API-PILOT-v0.1 game 2
contains only 2 late positions in total, so it cannot carry a late quota share.

Sharpness is recorded from the existing post game analysis, as a covariate only.
The engine never touches a prompt. In revision 2 it also no longer influences
selection, which removes the selection bias the first draft carried.

## Vocabulary: the four chained cells are two different things

A chained trial branches from a real conversation, and that conversation ran
under its game's protocol. So for each position:

| Source game | chain RAW | chain FEN |
| --- | --- | --- |
| RAW | **native chain** | **switched current turn** |
| FEN | **switched current turn** | **native chain** |

These names appear in the output. They are not cosmetic.

**Primary context analysis: native chain against fresh, same protocol.**

* RAW source positions: fresh RAW against chain RAW
* FEN source positions: fresh FEN against chain FEN

That asks the actual question: what happened when the real accumulated
conversation that produced this position was added, without changing the
protocol of the sampled turn.

**Secondary: the current turn switch diagnostic.** The cross protocol chained
cells ask something different and still useful: if only the current turn's
representation is changed, after a history built under the other protocol, does
legality get rescued or damaged. Reported separately, never folded into the
chain effect.

## Two limitations that are design constraints, not caveats

**The hybrid cells are not a flaw to be removed.** They cannot be removed while
branching from real chains, and naming them correctly is the fix. See above.

**Six game contexts, and no attempt to model that away.** Forty positions drawn
from six games is forty boards but six openings, six opponents and six
conversations. A random game effect cannot be estimated from six clusters, and
will not be pretended into existence with sophisticated modelling. The reporting
discipline instead: counts by arm, position clustered uncertainty, game id and
source protocol shown for every position, an explicit statement that only six
game contexts exist, and **no population level legality rate claim**.

The corpus is frozen from the **six games completed at freezing time**: the RAW
pair, the FEN 1320 pair and the FEN 1500 pair. It does not wait for later ladder
games, because then the reliability corpus would depend on how far Astra happens
to climb. The corpus file records the six game ids and the sha256 of each
published record before any sampling, and **no position is added after
freezing**.

## Preregistered analysis, in this order

1. **Total illegal responses by arm**, as counts, with native chain and
   switched current turn cells shown separately, never summed into one
   "chained" number.
2. **Primary: native chain against fresh, within protocol.** RAW source
   positions fresh RAW against chain RAW, FEN source positions fresh FEN against
   chain FEN.
3. **Secondary: the current turn switch diagnostic**, both directions.
4. **RAW against FEN**, pooling context. Supporting and descriptive.
5. **Chain depth pattern** across the three strata.
6. **Position and game level clustering**: whether failures recur on the same
   boards, whether the same wrong move recurs, and whether failures concentrate
   in one source game. Heavy clustering inside a single game is itself a result
   and is reported as one.

Exact counts and uncertainty first, p values last if at all. With sparse
failures, `chain RAW 4/80 against fresh RAW 1/80` carries more information than
a regression coefficient made to stand in for the whole story.

## Power, stated plainly and in advance

At an underlying failure rate near 2%, 320 responses yields roughly **6 failures
in expectation**. Under an optimistic independence approximation a 2% against 8%
contrast has moderate power at best, and clustering by board lowers effective
power further.

> **This study is designed to detect a large protocol or context effect. It is
> not powered to rule out small differences.**

A null result means "no large effect was detected here", never "the protocols are
equally reliable".

## What has to be built

* a corpus builder that samples and stratifies the 40 positions from published
  records and writes the frozen corpus file, with its random seed, before any
  call;
* a batch runner over corpus x arm x trial with the study guard, the stage 1
  futility check and per response recording;
* an analysis pass producing the arm table with position clustered intervals.

None of it is built yet, on purpose.

## Status

Design approved with a $40 guard. **Execution not started.** It will not start
while a scored game is running, and the corpus is frozen only after the 1500 pair
closes.

## Amendment C1: the execution order

Written after the 1700 pair closed and **before any study response existed**.
The study has generated nothing; the four fresh and chain probe arms from the
ply 45 diagnostic are a different, already published experiment.

**The problem.** The frozen corpus defines the sample, not an execution order.
`corpus.json` stores positions sorted by `(game_id, depth)` for readability, so
a naive "first 20" would have been **20 FEN source positions drawn from four of
the six games and 0 RAW**. Since Stage 1 consumes the first 20 positions, the
futility stop would have depended on an alphabetical artefact rather than on the
naturalistic sample.

**The fix, and its limits.** `tools/stage1_order.py` defines, once and
deterministically, which 20 of the already frozen 40 form Stage 1 and the order
all 40 run in. It adds, removes and substitutes nothing, uses no engine
information, and does not modify the corpus, which it pins by sha256
`5f76aded8968c102c2a4b5f615611c8eebb859695948d907b36181c0181232e0`.

**Targets, all met exactly** at seed 20260908:

| | Target | Achieved |
| --- | --- | --- |
| Source protocol | 8 RAW, 12 FEN | 8 RAW, 12 FEN |
| Per game | 4, 4, 3, 3, 3, 3 | 4, 4, 3, 3, 3, 3 |
| Side to move | 10 White, 10 Black | 10 White, 10 Black |
| Depth strata | 7 early, 6 middle, 7 late | 7 early, 6 middle, 7 late |

Stage 2 is the complementary 20. The order within each stage is a seeded
shuffle, so execution order is also defined rather than left to whatever a loop
happens to do.

Frozen in `results/diagnostics/reliability-study-v0.1/stage1-order.json`.

## Amendment C2: the chain arms branched from the wrong response

Applied after 8 of 160 Stage 1 responses, before any scored response exists under
the corrected frame.

**The defect.** The corpus stored each position's own `response_id`, and the
runner branched the chain arms from it, then sent that same turn's prompt. The
conversation being continued therefore already contained the answer to the
question being asked.

**How it was found.** The first eight responses were inspected for pace, and the
four chain responses had returned **6 output tokens with 0 reasoning tokens** and
the move actually played in the source game, against 1,878 to 4,575 reasoning
tokens in the fresh arms. The run was stopped immediately and the branch id was
compared with the sampled turn's own id: byte identical.

**Why the chain responses are void.** They measure whether the model repeats an
answer already in its context. That is not the question this study asks.

**What was done.**

* The run stopped at 8 of 160 responses. Diagnostic spend $0.98.
* The four chain responses are void. The four fresh responses were technically
  valid and are **deliberately discarded** so that the study has one clean
  execution frame rather than a file spanning two.
* The defective file is retained for audit as
  `VOID_DIAGNOSTIC_DO_NOT_SCORE-responses-stage1.jsonl` with its sha256, and is
  excluded from every Track 2 result, denominator, statistic and published
  artifact.
* C2 adds `chain_from_response_id` and `chain_from_ply` to all 40 positions: the
  immediately preceding model turn. **No position was added, removed, resampled
  or reordered**; keys, source games, protocol assignment, strata, colour
  balance, the Stage 1 ordering and the seed are unchanged, which is asserted by
  regenerating the ordering from the amended corpus at the same seed and
  comparing.
* No Track 1 game or scored result was affected. Nothing the study did was
  stored: `store=false` on every request.
* C2 was committed before any restarted response was observed.

**Corpus digests.** Before `5f76aded8968c102c2a4b5f615611c8eebb859695948d907b36181c0181232e0`,
after `386416d2d94201099d8ecc40eed1e9e2e79b65bbc913ec5f4fed334f950432ab`.

**Why the tests changed too.** A test asserting only
`chain_from_response_id != response_id` would forbid this exact bug and permit
others. The invariants now assert what the parent must **be**: the immediately
preceding model turn, with nothing between them in the model's turn sequence,
cross checked against the game's own recorded `previous_response_id`, with the
parent strictly earlier, its board different, its prompt different, no later FEN
in its prompt, never a later or foreign response id, and the whole relationship
matching what `--chain-from-ply 43` did for ply 45 in the original diagnostic.

## Disclosure: the corpus contains the known failure position

Blind sampling under the frozen frame drew **API-PILOT-v0.1 game 2, ply 45**, the
position that produced the only illegal move in scored play and that the ply 45
diagnostic already probed twenty times (19 legal, 1 illegal).

It is 1 of 40 positions, it was selected before anyone looked at the sample, and
removing it now would be post hoc selection, which is a worse problem than
keeping it. It is disclosed here so that a failure at that position in Stage 1 is
read as the least surprising failure available rather than as an independent
discovery, and so that anyone reading the arm counts knows one cell of the corpus
has prior evidence attached to it.
