# Experiment protocol

This is the operating procedure for a benchmark cycle. The code enforces what it
can; this document covers the parts that live with the operator.

## 1. Fix the conditions before collecting

Decide and write down, before the first game:

* the model and the exact interface used to reach it (for the first cycle:
  GPT-6 Astra through Codex, one fresh context per move);
* the protocols in scope (`raw`, `fen`, `legal`);
* the Stockfish Elo rungs (for example 1350, 1600, 1900);
* the number of games per cell of the matrix, and colour balance within a cell;
* the search limit (`--nodes`, so the cell is reproducible).

A cell is one (protocol, Elo, colour) combination. Half the games of a rung
should be played with the AI as White and half as Black.

## 2. Game identifiers

Use a readable, sortable id so records can be grouped later without parsing:

```
<model>-<protocol>-<colour>-<elo>-<nnn>
astra-raw-w-1500-001
```

## 3. Per game checklist

1. Start a fresh model context.
2. Run `bzbench play` with the cell's configuration and the game id.
3. For each turn: copy the whole prompt block, paste it into the model, paste
   the model's reply back verbatim.
4. Do not correct, re-ask, or hint. A malformed reply is a result.
5. When the game ends, note anything unusual in a lab log alongside the game id
   (model refusals, latency, interface glitches).
6. Run the analysis pass, either with `--analyze` during the run or afterwards
   with `bzbench analyze`.

## 4. Threats to validity worth tracking

* **Context carryover.** If the same model context is reused between turns or
  between games, the model has memory the protocol did not grant. Fresh context
  per turn is the strict reading; whatever is chosen must be recorded and kept
  constant.
* **Operator leakage.** Any word from the operator that is not the prompt is a
  confound, including reactions to a move.
* **Response drift.** Models change. Record the model build string in the
  `--notes` field for every cycle.
* **Engine version.** Stockfish version and the effective Elo are recorded
  automatically; do not mix versions inside a cell.
* **Time.** `--max-move-seconds` measures wall clock, which in manual mode
  includes the operator. Leave it unset for manual runs unless the run is being
  timed on purpose.

## 5. Reporting

Report per cell: games, win/draw/loss, score rate, games with an illegal move,
total illegal moves, mean plies, mean accuracy and mean average centipawn loss.
`bzbench summarize --json` produces exactly these fields.

Report illegal moves separately from playing strength. A model that plays well
but hallucinates a piece every thirty moves is a different finding from a model
that plays legally and badly, and averaging them hides both.
