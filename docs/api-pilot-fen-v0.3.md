# API-PILOT-FEN-v0.3

Track 1, strength. The third rung of the FEN ladder. Frozen before the first API
call.

## The question

The 1500 pair was won 2-0, which triggered this rung under the amended climbing
rule. It did not establish that Astra is stronger than 1500. What it did show is
a gap worth watching: **the results held while the move quality measurements got
clearly worse**, ACPL roughly tripling from the 1320 pair and the first three
blunders of the FEN programme appearing.

> Does the result finally catch up with the deterioration already visible in the
> move quality measurements?

## Design

Paired games, one per colour. **Two changes from API-PILOT-FEN-v0.2, one of them
chess facing and one operational.**

| | Game 1 | Game 2 |
| --- | --- | --- |
| Model | gpt-6-astra | gpt-6-astra |
| Reasoning effort | high | high |
| Protocol | FEN | FEN |
| Astra colour | White | Black |
| **Stockfish Elo** | **1700** | **1700** |
| Search limit | 200,000 nodes | 200,000 nodes |
| Threads / hash | 1 / 16 MB | 1 / 16 MB |
| Output ceiling | 12,000 tokens | 12,000 tokens |
| **Spend guard** | **$50 metered** | **$50 metered** |
| Conversation | fresh chain, `store=true` | fresh chain, `store=true` |
| Prompt version | 2 | 2 |
| Max plies | 400 | 400 |

**Chess facing change: Stockfish Elo 1500 to 1700. That is the only one.**

**Operational amendment O1: the per game spend guard rises from $25 to $50.**
Recorded here, before the pair, not adapted during a game.

The sizing argument, from the 93 response game at 1500 and nothing else. In that
game $7.31 of $11.50 was input and $4.19 was output. Using that single run as a
planning model, with input volume approximately quadratic in response count
because the whole transcript is resent each turn, and everything else roughly
linear, $25 is reached at about **147 model responses, roughly 294 plies**, and
the existing 400 ply termination is reached at about **$43**. A $50 guard makes
the 400 ply rule realistically reachable while keeping a genuine runaway stop.

This is a sizing estimate from one game, not a prediction of what a 1700 game
costs. If a 1700 game aborts on the guard anyway, that is a result to report, not
a reason to raise the guard mid ladder.

## Explicitly not changed

* **No wall clock timeout.** The 1500 black game spent 42 minutes in API waits
  and was progressing throughout. Latency is an operational result, not an abort
  condition.
* **No conversation or context transport optimisation.** Resending the full
  transcript is now an interesting engineering problem, and changing it during
  the ladder could change model behaviour and destroy rung comparability. It
  waits until the ladder is done or is paused deliberately.
* Referee, SAN validation, illegal move rule, failure taxonomy, prompt structure,
  bare SAN response requirement, cost capture, analysis pass: untouched.

## Climbing rule

Carried over from API-PILOT-FEN-v0.2 amendment A1, unchanged:

| First pair score | Action |
| --- | --- |
| 2-0 | freeze the next rung |
| 1.5-0.5 | two more games at 1700 before any climbing decision |
| 1-1 | two more games at 1700 before any climbing decision |
| 0.5-1.5 or 0-2 | stop the climb and review, do not automatically add games |

No four game threshold is defined in advance. After four scored games at a rung,
the complete rung comes back for a ruling.

Scoring: win 1, draw 0.5, loss 0. A loss on an illegal move response counts as a
loss for the rung score, is reported as incomplete for strength purposes, has its
position added to the Track 2 corpus, and is not re-run. An infrastructure, spend
or output limit abort is re-run once at the same configuration with both attempts
recorded, since neither is a chess result.

## Operating rules

* execution commit recorded before the first call and checked before each game;
* no commit to this repository between the two games;
* fresh conversation per game;
* no diagnostic runs while a scored game is running;
* the Track 2 corpus was frozen before this rung began and does not include any
  1700 position.

## Commands

Game 1, Astra as White:

```bash
python3 -m bzbench.cli play \
  --model "gpt-6-astra" --adapter openai --api-model gpt-6-astra \
  --reasoning-effort high --protocol fen --color white \
  --elo 1700 --stockfish stockfish --nodes 200000 --threads 1 --hash-mb 16 \
  --max-output-tokens 12000 --max-cost-usd 50 \
  --game-id API-PILOT-FEN-v0.3-g1-astra-white \
  --analyze --depth 18
```

Game 2, Astra as Black:

```bash
python3 -m bzbench.cli play \
  --model "gpt-6-astra" --adapter openai --api-model gpt-6-astra \
  --reasoning-effort high --protocol fen --color black \
  --elo 1700 --stockfish stockfish --nodes 200000 --threads 1 --hash-mb 16 \
  --max-output-tokens 12000 --max-cost-usd 50 \
  --game-id API-PILOT-FEN-v0.3-g2-astra-black \
  --analyze --depth 18
```
