# API-PILOT-v0.1

The first two games played by GPT-6 Astra through the API. Prepared, not
started: neither command below is run until the operator says so.

## Design

Two games, identical in everything except colour, so that a first result is not
a statement about one side of the board.

| | Game 1 | Game 2 |
| --- | --- | --- |
| Model | gpt-6-astra | gpt-6-astra |
| Reasoning effort | high | high |
| Protocol | RAW | RAW |
| Astra colour | White | Black |
| Stockfish Elo | 1320 | 1320 |
| Stockfish limit | 200,000 nodes, frozen | 200,000 nodes, frozen |
| Opening | standard starting position, no book | same |
| Conversation | fresh chain | fresh chain, no shared context |
| Spend guard | $15 | $15 |

A fixed node limit, not a movetime, so the opponent is reproducible on this
Stockfish build regardless of what else the machine is doing.

## Commands

Preflight, which starts no game:

```bash
python3 -m bzbench.cli preflight \
  --adapter openai --api-model gpt-6-astra --reasoning-effort high \
  --protocol raw --elo 1320 --nodes 200000 --max-cost-usd 15 \
  --estimate-moves 60 --estimate-input-tokens 2000 --estimate-output-tokens 6000
```

Game 1, Astra as White:

```bash
python3 -m bzbench.cli play \
  --model "gpt-6-astra" \
  --adapter openai \
  --api-model gpt-6-astra \
  --reasoning-effort high \
  --protocol raw \
  --color white \
  --elo 1320 \
  --nodes 200000 \
  --max-cost-usd 15 \
  --game-id API-PILOT-v0.1-g1-astra-white \
  --notes "API-PILOT-v0.1 game 1, RAW, Astra White, Stockfish 1320 at 200k nodes" \
  --analyze --depth 18
```

Game 2, Astra as Black, fresh conversation:

```bash
python3 -m bzbench.cli play \
  --model "gpt-6-astra" \
  --adapter openai \
  --api-model gpt-6-astra \
  --reasoning-effort high \
  --protocol raw \
  --color black \
  --elo 1320 \
  --nodes 200000 \
  --max-cost-usd 15 \
  --game-id API-PILOT-v0.1-g2-astra-black \
  --notes "API-PILOT-v0.1 game 2, RAW, Astra Black, Stockfish 1320 at 200k nodes" \
  --analyze --depth 18
```

Each `play` invocation builds its own adapter, so game 2 cannot inherit game 1's
conversation. Run them one after the other, not in parallel, so a rate limit in
one does not corrupt the other's timing.

## After the games

```bash
python3 -m bzbench.cli summarize games --json > docs/results/api-pilot-v0.1.json
python3 -m bzbench.cli show games/API-PILOT-v0.1-g1-astra-white/game.json
```

Report together, never separately: result, illegal move count, termination,
accuracy, average centipawn loss, total tokens, reasoning tokens and dollar
cost. A high accuracy in a game that was lost by move 15 says very little on its
own.

## Stop conditions

Stop the pilot and report rather than continuing if any of these happens:

* a game ends with `cost_limit_abort` or `token_limit_abort`, which means the
  $15 guard is below what one game costs at this effort;
* a game ends with any `api_*` termination twice in a row, which means the
  transport, not the model, is what is being measured;
* the model answers with prose on the first move of both games, which is an
  output discipline result worth reporting before spending more.
