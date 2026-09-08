# API-PILOT-FEN-v0.2

Track 1, strength. The second rung of the FEN ladder. Frozen before the first
API call.

## The question

API-PILOT-FEN-v0.1 produced two wins out of two at Elo 1320 with 61 legal
responses out of 61, so 1320 is not a useful ceiling. This rung asks a single
question:

> Does Astra still win under FEN when the opponent is stronger?

It is not a reliability experiment. The mechanism behind the one illegal move
observed under RAW is being investigated separately in Track 2 and does not gate
this ladder.

## Design

Paired games, one per colour, at the next rung. **The only thing that changes
from API-PILOT-FEN-v0.1 is the Stockfish Elo.**

| | Game 1 | Game 2 |
| --- | --- | --- |
| Model | gpt-6-astra | gpt-6-astra |
| Reasoning effort | high | high |
| Protocol | FEN | FEN |
| Astra colour | White | Black |
| **Stockfish Elo** | **1500** | **1500** |
| Search limit | 200,000 nodes | 200,000 nodes |
| Threads / hash | 1 / 16 MB | 1 / 16 MB |
| Output ceiling | 12,000 tokens | 12,000 tokens |
| Spend guard | $25 metered | $25 metered |
| Conversation | fresh chain, `store=true` | fresh chain, `store=true` |
| Prompt version | 2 | 2 |
| Opening | standard start, no book | same |

Unchanged and not to be touched: reasoning effort, node budget, threads, hash,
the 12,000 token ceiling, the prompt structure, the bare SAN response
requirement, the referee, SAN validation, the illegal move rule, the failure
taxonomy, the cost capture and the analysis pass.

## Climbing rule, fixed in advance

* **Convincing pair, two wins:** freeze the next rung at **1700**.
* **Split, one win and one loss on chess:** do not climb. Add two more games at
  1500, one per colour, before any decision.
* **Any game ends on an illegal move response:** the rung result is reported as
  incomplete for strength purposes. The illegal move is still scored as a loss
  under the frozen rule, and the position is added to the Track 2 corpus. Do not
  re-run the game.
* **Any infrastructure, spend or output limit abort:** re-run that game once at
  the same configuration and record both attempts, since neither is a chess
  result.

No stopping rule based on the result of game 1 of the pair. Both games are run.

## Reporting

Three dimensions, never collapsed, per `docs/reporting-dimensions.md`. Carry the
descriptive columns forward across rungs so a pattern has somewhere to appear:
Astra ACPL and accuracy, **opponent ACPL and accuracy**, legal responses over
total, reasoning tokens per move, latency, cost.

The FEN pair at 1320 posted lower ACPL than the RAW pair while facing better
opponent play. That observation is carried, not explained. Ten to twenty games
would be needed before revisiting whether the protocol affects chess quality.

## Operating rules

* execution commit recorded before the first call and checked before each game;
* no commit to this repository between the two games;
* fresh conversation per game, no conversation shared with any other game or
  probe;
* diagnostics do not run while a scored game is running.

## Commands

Game 1, Astra as White:

```bash
python3 -m bzbench.cli play \
  --model "gpt-6-astra" --adapter openai --api-model gpt-6-astra \
  --reasoning-effort high --protocol fen --color white \
  --elo 1500 --stockfish stockfish --nodes 200000 --threads 1 --hash-mb 16 \
  --max-output-tokens 12000 --max-cost-usd 25 \
  --game-id API-PILOT-FEN-v0.2-g1-astra-white \
  --analyze --depth 18
```

Game 2, Astra as Black:

```bash
python3 -m bzbench.cli play \
  --model "gpt-6-astra" --adapter openai --api-model gpt-6-astra \
  --reasoning-effort high --protocol fen --color black \
  --elo 1500 --stockfish stockfish --nodes 200000 --threads 1 --hash-mb 16 \
  --max-output-tokens 12000 --max-cost-usd 25 \
  --game-id API-PILOT-FEN-v0.2-g2-astra-black \
  --analyze --depth 18
```
