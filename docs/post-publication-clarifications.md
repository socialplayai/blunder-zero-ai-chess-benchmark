# Post publication clarifications

The tag `astra-chess-benchmark-v0.1` at commit `5bf0561` is the immutable
execution snapshot and is **not moved, retagged or rewritten**. Everything below
is a documentation correction made on `main` after publication. No result, game
record, analysis figure, corpus, response artifact or hash has changed, and none
ever will under this heading.

## C1. The README described the pilot, not the published programme

**What was wrong.** The README opened by saying the first model was relayed by
hand through Codex, and called RAW the headline condition. Both were true of the
first pilot and neither was true of the scored programme, which ran through the
OpenAI API with zero tools and used FEN as the strength protocol. The evidence
ledger already said FEN had become the primary strength protocol, so the
repository contradicted itself.

**What it says now.** A table at the top separates the initial manual pilot from
the scored published programme, names FEN as the strength track, and describes
RAW as a separate state tracking and reliability condition.

## C2. The evidence ledger was stale

**What was wrong.** It stated it was last updated after API-PILOT-FEN-v0.1 and
the ply 45 diagnostic, and therefore stopped before the 1700 games and before
RELIABILITY-STUDY-v0.1 completed. The README points readers at it as the
authoritative record of what has and has not been shown, which made the staleness
worse than a normal out of date document.

**What it says now.** All six ladder games, the full legality table including the
1700 pair and the 329 of 329 total, and the completed reliability study with its
futility stop.

## C3. "Strength bracket" is withdrawn

**What was wrong.** The closure document and README said the result "brackets its
playing strength between the 1500 and 1700 rungs". That reads as a rating band.
Two games per rung cannot separate a strength boundary from the variance of two
games, and the opponent is a limiter setting rather than a rated player, so there
is no scale on which to place a bracket.

**What it says now.** Only what happened: *in the six game FEN ladder, Astra won
both games at the Stockfish `UCI_LimitStrength` 1320 and 1500 settings, then lost
both at 1700.*

## C4. Limiter settings are not Elo ratings

**What was wrong.** Several documents wrote "Elo 1320" and "strength limited
Stockfish 18 at Elo 1500" in ways that invite reading the opponent as a
1500 rated player.

**What it says now.** *Limiter setting* or *rung* throughout, with the full
configuration named where it matters: Stockfish 18, `UCI_LimitStrength` enabled,
the setting, and 200,000 nodes per move. A limited engine does not play like a
human of the nominal rating, and the fixed node budget makes this configuration
specific to this benchmark.

## What did not change

The six game records, every prompt and raw response, the analysis figures, the
reliability corpus and its digest, the 160 scored responses, the manifests and
every hash. Those are what the tag protects, and they are byte identical to the
published snapshot.
