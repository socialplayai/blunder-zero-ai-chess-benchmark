# API-PILOT-FEN-v0.1

A separate experiment, not a continuation of API-PILOT-v0.1. Frozen before the
first API call.

## The question

API-PILOT-v0.1 produced one win and one loss, and the loss came from an illegal
move in a winning position rather than from bad chess. That separates two things
that a single strength number would confuse: what the model chooses, and whether
it still knows where the pieces are.

This experiment asks exactly one question:

> Does supplying authoritative board state remove the failure mode?

It does not ask whether Astra can beat a stronger opponent. The Elo ladder stays
frozen until RAW legality is understood.

## Design

Two games, one per colour, identical to the RAW pair in everything except the
protocol.

| | Game 1 | Game 2 |
| --- | --- | --- |
| Experiment | API-PILOT-FEN-v0.1 | API-PILOT-FEN-v0.1 |
| Model | gpt-6-astra | gpt-6-astra |
| Reasoning effort | high | high |
| **Protocol** | **FEN** | **FEN** |
| Astra colour | White | Black |
| Stockfish | 18, Elo 1320, `UCI_LimitStrength` on | same |
| Search limit | 200,000 nodes | 200,000 nodes |
| Threads / hash | 1 / 16 MB | 1 / 16 MB |
| Output ceiling | 12,000 tokens | 12,000 tokens |
| Spend guard | $25 metered | $25 metered |
| Conversation | fresh chain, `store=true` | fresh chain, `store=true` |
| Prompt version | 2 | 2 |
| Opening | standard start, no book | same |

What FEN changes, and the complete list of it: the prompt gains two lines, a
`Current position (FEN):` header and the FEN string. Instructions, move history,
the bare SAN response requirement, the referee, SAN validation, the illegal move
rule, the failure taxonomy, the cost capture and the analysis pass are all
unchanged and are the same code objects the RAW pair used.

FEN mode still supplies **no legal move list**. A model that is handed the
position and still names an impossible move has made a chess reasoning error,
not a bookkeeping error, and that distinction is the point of not jumping
straight to LEGAL.

## Preregistered analysis

The comparison table this fills in:

| Protocol | White | Black |
| --- | --- | --- |
| RAW | win, 31/31 legal | loss by illegal move, 22/23 legal |
| FEN | to be filled | to be filled |

Reported in the three dimensions of `docs/reporting-dimensions.md`, never
collapsed:

1. **Chess quality**: ACPL, accuracy, judgement counts, result.
2. **Protocol reliability**: legal responses over total responses, malformed
   responses, state tracking failures, the ply of any failure.
3. **Operational**: latency, tokens, cost, infrastructure incidents.

Interpretation agreed in advance, so it is not chosen after seeing the numbers:

* **0 legality failures across both FEN games, with chess quality similar to the
  RAW pair.** Evidence that the RAW bottleneck is state reconstruction rather
  than chess ability. Two games is still two games: this is a direction, not a
  measurement.
* **Legality failures under FEN as well.** The failure is not state
  reconstruction, and supplying the position does not fix it. That would point
  at move generation from a known position, and LEGAL would become the next
  probe.
* **Chess quality materially worse under FEN.** Worth reporting as a surprise
  rather than explaining away; it would suggest the move history itself carries
  something the FEN does not.

No stopping rule based on the result of game 1 of the pair: both games are run
unless an infrastructure, spend, or output-limit abort occurs.

## Operating rules for this pair

Carried over from the API-PILOT-v0.1 deviation D1:

* the execution commit is recorded below before the first call;
* **no commit is made to this repository between the two games**;
* the runner HEAD is checked against the execution commit before each game;
* neither game shares a conversation with the other or with any probe.

**Execution commit:** recorded in `results/api-pilot-fen-v0.1/DEVIATIONS.md`
after the pair completes, and verifiable in each game record's
`environment.bzbench_commit`.

## Commands

Game 1, Astra as White:

```bash
python3 -m bzbench.cli play \
  --model "gpt-6-astra" --adapter openai --api-model gpt-6-astra \
  --reasoning-effort high --protocol fen --color white \
  --elo 1320 --stockfish stockfish --nodes 200000 --threads 1 --hash-mb 16 \
  --max-output-tokens 12000 --max-cost-usd 25 \
  --game-id API-PILOT-FEN-v0.1-g1-astra-white \
  --analyze --depth 18
```

Game 2, Astra as Black:

```bash
python3 -m bzbench.cli play \
  --model "gpt-6-astra" --adapter openai --api-model gpt-6-astra \
  --reasoning-effort high --protocol fen --color black \
  --elo 1320 --stockfish stockfish --nodes 200000 --threads 1 --hash-mb 16 \
  --max-output-tokens 12000 --max-cost-usd 25 \
  --game-id API-PILOT-FEN-v0.1-g2-astra-black \
  --analyze --depth 18
```

## The diagnostic probe is not part of this experiment

`tools/failure_probe.py` replays the exact API-PILOT-v0.1 game 2 failure
position under RAW and FEN, several independent times. It is faster causal
evidence than waiting for a game to wander into a hard tracking state, and it is
**not a game**: no result, no Elo evidence, written to an untracked
`diagnostics/` path, `store=false` on every trial so it cannot seed or
contaminate any game conversation. Its output is reported separately and is
never mixed into a games table.
