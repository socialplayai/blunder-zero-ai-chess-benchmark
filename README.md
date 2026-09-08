# BlunderZero AI Chess Benchmark

A small, deliberately strict benchmark for one question:

> How well does a general purpose frontier AI model play chess when it has no
> chess engine, no opening book, no tablebase and no chess specific tooling?

The first model under test is GPT-6 Astra, relayed by hand through Codex. The
first opponent is Stockfish at a configurable Elo. Experimental integrity is
valued above convenience everywhere the two conflict.

## The four roles, kept apart

The single most important property of this benchmark is that the model never
sees engine output. Four components exist, and only one of them talks to the
model.

| Role | Where | Talks to the model | Sees the engine |
| --- | --- | --- | --- |
| **AI player** | `bzbench/adapters/` | yes | never |
| **Referee** | `bzbench/referee.py` | only through the protocol layer | yes, but only to ask for a move |
| **Playing opponent (Stockfish)** | `bzbench/engine.py`, `StockfishOpponent` | no | is the engine |
| **Post-game analysis (Stockfish)** | `bzbench/analysis.py`, `AnalysisEngine` | no | is the engine |

* The **AI player** receives a prompt built by `bzbench/protocol.py` and returns
  one line of text. Its interface is `propose_move(prompt, view)`. There is no
  engine handle in that signature and no way to obtain one.
* The **referee** owns the board. It validates every AI move, asks the opponent
  for its reply, and records the game. It passes the opponent's move to the
  board, never to the prompt builder.
* The **playing opponent** answers exactly one question, "what is your move",
  and returns a `chess.Move`. It is configured with `info=INFO_NONE`, so no
  score, depth or principal variation is even parsed, let alone recorded in a
  place the prompt builder could read.
* The **post-game analysis** is a second, full strength Stockfish process. It
  starts only after a game record is closed, and its output goes into the
  record and the reports. The referee does not import that module.

`bzbench/protocol.py` is the only choke point through which information reaches
the model, and it takes a board plus a move history, nothing else.

## Information protocols

Each game is played under exactly one protocol, recorded in the PGN header and
in the JSON record.

| Protocol | Instructions | Move history | FEN | Legal moves |
| --- | --- | --- | --- | --- |
| `raw` | yes | yes | no | no |
| `fen` | yes | yes | yes | no |
| `legal` | yes | yes | yes | yes |
| `visual` | reserved for a future board image experiment, not implemented |

`raw` is the headline condition: the model must maintain the position in its own
head from the move list alone. `fen` isolates board reconstruction from chess
understanding. `legal` isolates chess understanding from legal move generation.
`visual` deliberately raises `NotImplementedError` everywhere rather than
silently falling back to a text protocol.

The legal move list in `legal` mode is sorted alphabetically, so its ordering
carries no engine ranking.

## Move legality: no repairs, ever

The AI must answer with exactly one move in standard algebraic notation and
nothing else. The referee applies one normalisation and one only: leading and
trailing whitespace is stripped. Then:

* the token must match a strict SAN pattern, so a UCI string such as `e2e4` is
  rejected;
* it must equal the SAN the referee itself generates for a legal move, ignoring
  only the `+` or `#` suffix, so `e4` and `e4+` are the same claim;
* an under specified move that could mean more than one legal move is rejected
  as ambiguous rather than resolved.

Anything that fails ends the game immediately as a loss for the AI, with
termination `illegal_move`. There is no retry, no reinterpretation, no "did you
mean". The raw response is stored verbatim in the record either way.

Other terminations: `checkmate`, `stalemate`, `insufficient_material`,
`seventyfive_moves`, `fivefold_repetition`, `resignation`, `time_forfeit`
(when `--max-move-seconds` is set and exceeded), `max_plies`, `aborted`,
`engine_error`.

## Install

```bash
python3 -m pip install -r requirements.txt   # or: pip install -e ".[dev]"
brew install stockfish                       # any UCI Stockfish on PATH
```

## Run a game

The `manual` adapter is the one to use for the first experiments. It prints a
prompt block, you paste it into the model, and you paste the model's reply back.

```bash
python3 -m bzbench.cli play \
  --model "gpt-6-astra" \
  --protocol raw \
  --color white \
  --adapter manual \
  --elo 1500 \
  --nodes 200000 \
  --game-id astra-raw-w-1500-001 \
  --analyze
```

At each turn you get a block like this, and nothing else reaches the model:

```
========================================================================
COPY THE BLOCK BELOW INTO THE MODEL  (ply 4, protocol raw)
========================================================================
You are playing a game of chess as White.

You are playing from your own chess understanding alone. No chess program,
opening reference, endgame reference or analysis tool is available to you, and
no output from any such tool appears below. If a move you give is illegal in
the position, the game is immediately recorded as a loss.

Moves played so far (chronological, standard algebraic notation):
1. e4 e5 2. Nf3 Nc6

It is your move (White, move 3).
Respond with exactly one chess move in standard algebraic notation (SAN) and
nothing else. ...
========================================================================
Paste the model response (one SAN move), or :resign / :abort:
```

Type `:resign` to record a resignation (a loss) or `:abort` to end the session
without a result.

### Operator discipline

The prompt is the experiment. Paste it whole and unedited into a fresh context,
and paste back exactly what the model returned, including any surrounding text
if the model emitted some, because a response that is not a bare SAN move is a
result, not an accident to be tidied up. Do not tell the model what the engine
is doing, do not answer its questions, and do not carry commentary between
turns beyond the prompt itself.

## Playing through the OpenAI API

The `openai` adapter runs the same experiment without an operator. It is the
same prompt, the same referee and the same records; only the transport differs.

```bash
export OPENAI_API_KEY=...        # the only place the key is ever read from

python3 -m bzbench.cli preflight --adapter openai --elo 1320 --nodes 200000

python3 -m bzbench.cli play \
  --model "gpt-6-astra" --adapter openai --api-model gpt-6-astra \
  --reasoning-effort high --protocol raw --color white \
  --elo 1320 --nodes 200000 --max-cost-usd 15 \
  --game-id API-PILOT-v0.1-g1 --analyze
```

What the model is given: the benchmark prompt, and nothing else. Every request
carries `tools: []`. There is no function calling, no code execution, no web or
file access, no structured output schema, and no engine, chess library or
opening database anywhere near the model. The adapter does not parse the
position, does not generate moves, and does not extract a move from the reply.
It hands the raw visible text to the referee, which judges it under the frozen
rules: malformed or illegal is an immediate loss, with no retry.

Within a game the conversation is one response chain (`previous_response_id`
with `store=true`), so the model keeps its own earlier reasoning. Every game
starts a fresh chain and no context crosses games.

Reasoning effort is `--reasoning-effort`, default `high`. An unsupported level
fails before the game starts and is never silently replaced.

Failures are separated from chess. An authentication failure, rate limit,
timeout, network error, provider 5xx or spend guard ends the game with no
result (`*`), never as a loss. Retries exist only for transient failures that
happen before a model response exists; a completed response is never retried.

Spend is bounded. `--max-cost-usd` (default $15 per game) and
`--max-total-tokens` are checked before every request, and reaching either ends
the game as `cost_limit_abort` or `token_limit_abort` with no chess result.
Prices come from `pricing/gpt-6-astra.json`, which records the rates, the moment
they were verified and the official source; reasoning tokens are billed inside
output tokens and are never counted twice.

The full specification, including the exact retry policy, the failure taxonomy
and the cost model, is in [docs/api-adapter.md](docs/api-adapter.md). The two
behaviour changes made to the frozen benchmark are listed in
[docs/changes-from-frozen.md](docs/changes-from-frozen.md).

### Preflight

`preflight` verifies a run without starting one: the key is present, the model
is reachable, the reasoning level is accepted, the request carries no tools,
Stockfish starts at the configured Elo, the configuration is valid, the output
directory is writable, and the pricing file is loaded and dated. It prints an
upper bound cost estimate for one game and compares it with the spend guard. The
optional live probe is one capped generation of a few tokens; `--no-probe`
verifies everything else and sends nothing.

## Post-game analysis

```bash
python3 -m bzbench.cli analyze games/astra-raw-w-1500-001/game.json --depth 18
```

Every position is evaluated once at fixed depth by a full strength engine. For
the move played at ply *i*:

```
cp_before = eval(position i)        from the mover's point of view
cp_after  = -eval(position i + 1)   same point of view
cpl       = clamp(max(0, cp_before - cp_after), 0, 1000)
```

Judgements use centipawn loss thresholds of 50 (inaccuracy), 100 (mistake) and
300 (blunder). Accuracy uses the Lichess win percentage model and is an
approximation of the Lichess number, not a reimplementation: per move
accuracies are averaged uniformly rather than volatility weighted. Read it as a
relative measure across games in this benchmark, not as a Lichess score.

One known property of that model, worth knowing before quoting a number: once a
position is completely lost, further bad moves cost very little win percentage,
so a player who is crushed early can still post a high accuracy. Report
accuracy, average centipawn loss, blunder counts and the result together.

Analysis output is written into `game.json` under `analysis`. It is produced
after the game is over and is never part of any prompt.

## Reports

```bash
python3 -m bzbench.cli summarize games            # table plus aggregate
python3 -m bzbench.cli summarize games --json     # machine readable
python3 -m bzbench.cli show games/<id>/game.json  # audit every prompt shown
```

Per game: result, win/draw/loss, illegal move count and first offending ply,
game length, termination reason, AI colour, Stockfish Elo, accuracy, average
centipawn loss, inaccuracies, mistakes, blunders.

## What is recorded

`games/<game_id>/game.pgn` is a standard PGN with the experiment in the
headers (`Protocol`, `AIColor`, `AIModel`, `Adapter`, `StockfishElo`,
`GameId`, `Termination`).

`games/<game_id>/game.json` is the full record:

* the complete configuration, including the requested and effective Stockfish
  Elo, the search limit actually used, engine options, and the random seed;
* the environment fingerprint (Python version, python-chess version, platform,
  repository commit);
* every half move with the FEN before it, timestamps and elapsed seconds;
* for every AI turn: the exact prompt shown, the raw response, the normalised
  response, whether it was legal, and the protocol filtered view it came from;
* every illegal move attempt with its position and the reason it was rejected;
* the post-game analysis, when it has been run.

That is enough to replay the game, re-derive every prompt, and re-run the
analysis.

### Reproducibility caveat

Stockfish at a fixed node count is reproducible on a given binary and version.
`--move-time-ms` is not: it depends on the speed of the machine that ran the
experiment. Prefer `--nodes` for anything you intend to compare across runs.
The AI player itself is only as reproducible as the model, which is why the
record keeps the raw responses rather than only the moves.

## Rehearsal harness

`tools/mock_operator.py` drives a real `bzbench play` session, playing both the
operator and the model with a seeded random mover that reconstructs the position
from the prompt text alone. It is a smoke test of the CLI and a live check that
the RAW prompt is sufficient to play. It is not a benchmark run, and the records
it produces describe a random mover.

```bash
python3 tools/mock_operator.py --protocol raw --elo 1350 --seed 11 --analyze
python3 tools/mock_operator.py --illegal-rate 1.0     # exercise the loss path
```

## Tests

```bash
python3 -m pytest -q              # everything
python3 -m pytest -q -m "not slow"  # skip the tests that start Stockfish
```

`tests/test_protocol_leakage.py` is the integrity suite, and
`tests/test_openai_adapter.py` extends it to the API path (no tools in any
request, no engine information in any request, no key in any artifact, API
errors never scored as losses). The API tests use a scripted fake client and
never spend a token.

`tests/test_protocol_leakage.py` is the integrity suite. It deliberately
attempts to get forbidden information into a prompt and asserts that it cannot:
no FEN in RAW mode, no legal move list in RAW or FEN mode, no engine
vocabulary, no numeric score, and a proof by construction that a RAW prompt is a
pure function of the move history (a fabricated board with the same history
produces a byte identical prompt). It also asserts statically that no module on
the path to the model imports the engine or the analysis code.

## Adding a model backend

Adapters are the extension point. Implement `AIPlayer.propose_move`, register
the class, and every protocol, report and integrity test applies unchanged.
`bzbench/adapters/openai_api.py` is the worked example:

```python
from bzbench import adapters
from bzbench.adapters.base import AIPlayer

class OpenAIResponsesAdapter(AIPlayer):
    name = "openai"

    def propose_move(self, prompt: str, view) -> str:
        ...  # return the model's raw text

adapters.register("openai", OpenAIResponsesAdapter)
```

Shipped: the manual adapter and the OpenAI Responses adapter. Planned: the
Anthropic API, and the reserved `visual` protocol with a rendered board.

## Layout

```
bzbench/
  config.py      experiment configuration, serialised into every record
  protocol.py    the only path to the model; builds protocol filtered prompts
  adapters/      manual, openai, reserved visual, registry
  pricing.py     pricing metadata, per move cost, spend and token guards
  engine.py      StockfishOpponent (plays) and AnalysisEngine (evaluates, later)
  referee.py     rules, strict SAN parsing, game loop, recording
  record.py      game record, PGN and JSON output
  analysis.py    post-game accuracy, ACPL, inaccuracies, mistakes, blunders
  stats.py       per game summaries and aggregates
  cli.py         preflight / play / analyze / summarize / show
pricing/
  gpt-6-astra.json  official rates with verification date and source
tools/
  mock_operator.py  rehearsal harness, not a benchmark run
tests/            unit tests plus the leakage suite
```
