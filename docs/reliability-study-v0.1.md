# RELIABILITY-STUDY-v0.1 (design, not authorised to run)

Track 2, reliability science. Entirely non Elo. No game is played, no result is
produced, nothing here enters a strength table.

## The question

> Does long accumulated conversation state increase the probability of an
> illegal move response, and does supplying the position authoritatively change
> that?

The ply 45 diagnostic answered this for one position and produced 19 legal
responses out of 20, with the single failure in the chain FEN arm. One position
cannot separate a property of the model from a property of that board. This
study replaces repetition on one position with coverage across many.

## Design

**Unit of analysis: one response.** Clustered by position and by source game.
Twenty answers from one board are one board, not twenty chess situations.

**Corpus: 20 to 30 distinct positions**, drawn from the four completed games,
stratified and preregistered before any call:

* **chain depth**: early (ply < 20), middle (20 to 40), late (> 40), so chain
  depth varies naturally with where the position sits in its game;
* **side to move**: both, roughly balanced;
* **board features**, included where they occur naturally, never constructed:
  in check, castling rights still available, a promotion available, an en
  passant capture available;
* **sharpness**: a mix of quiet positions and tactically messy ones, classified
  from the existing post game analysis. The engine is used **only to choose the
  corpus**, never in a prompt. The classification is written down before the
  first call so the selection cannot be adjusted after seeing results.

**Arms, 2x2, 3 trials each per position:**

| | RAW | FEN |
| --- | --- | --- |
| Fresh | independent conversation, `store=false` | same, plus the FEN lines |
| Chain | branched from that position's real stored response, `store=false` | same, plus the FEN lines |

Total: 20 positions x 4 arms x 3 trials = **240 responses**, or 360 at 30
positions.

Everything else is held at the frozen values: gpt-6-astra, reasoning `high`,
12,000 token ceiling, `tools: []`, bare SAN required, prompts from the frozen
builder, verdicts from the frozen validator. **No legal move list appears in any
prompt.** The validator computes legality after the response, as it always does.

## Preregistered analysis

Primary comparisons, each with the cluster structure respected:

1. **chain against fresh**, pooled across protocols. The mechanism hypothesis.
2. **FEN against RAW**, pooled across contexts. The protocol hypothesis.
3. The interaction, which is what the ply 45 diagnostic hinted at and could not
   resolve.

Report per arm legal rates with exact intervals, and cluster the uncertainty by
position rather than pretending 240 responses are 240 independent trials. State
in advance: with 240 responses and a failure rate near 2%, roughly five failures
are expected in total, so this study can detect a large effect and cannot detect
a small one. If the observed failure count is below three, report the arms and
decline to compare them.

Also recorded per response, descriptively: reasoning tokens, latency, cost, and
the distinct answers given, since repeated identical wrong answers on a position
say something different from scattered ones.

## Cost

Observed mean cost of a diagnostic response so far is $0.081 ($1.62 for 20
trials). Estimated **$19 for 240 responses**, **$29 for 360**. A per study spend
guard applies, proposed at $40, checked before every request in the same way the
per game guard is.

## What has to be built

* a corpus builder that samples and stratifies positions from published records
  and writes the frozen corpus file before any call;
* a batch runner over corpus x arm x trial, reusing the existing probe machinery,
  with the study level spend guard and per response recording;
* an analysis pass producing the per arm table with clustered intervals.

None of it is built. It is not built on purpose: the design should be argued with
before code exists to defend.

## Status

**Not authorised. Not run.** Track 1 does not wait for it.
