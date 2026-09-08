# Changes to the frozen benchmark

Frozen baseline: commit `9384be0`, "feat: engine-free chess benchmark for
frontier AI models".

The API work was required to leave the referee, the protocol definitions, SAN
validation, the Stockfish separation, PGN recording and the post-game analysis
alone. Two behaviour changes were unavoidable, and both are listed here rather
than buried in a diff. Everything else in this document is an addition that no
existing game path can observe.

## Behaviour change 1: prompt text, v1 to v2

**What changed.** `bzbench/protocol.py` now carries `PROMPT_VERSION = 2`. The
instruction block gained one sentence pair, "Play using only the information
supplied in this message. Do not use any external tool and do not use any
outside source of information", and the response rule now also names analysis
and markdown among the things the answer must not contain.

**Why.** The requirement that the model be told, in the prompt, not to use
external tools or information cannot be met by the v1 text. Putting it in an API
only field such as `instructions` was rejected: it would have made the manual
and API conditions differ in what the model is told, which is exactly the kind
of difference that is impossible to defend in a published comparison.

**What did not change.** RAW still carries instructions plus move history and
nothing else. FEN still adds the FEN only. LEGAL still adds the alphabetically
sorted legal moves only. The leakage suite passes unchanged, including the proof
that a RAW prompt is a pure function of the move history.

**Effect on existing data.** None. No real game had been played against the v1
text; the only records were mock operator rehearsals. Every turn now records
`view.prompt_version`, so v1 and v2 games could be separated if any v1 game ever
mattered.

## Behaviour change 2: a game can now end with no result

**What changed.** The referee catches `PlayerInfrastructureError` and ends the
game with `result = "*"`, the failure kind as the termination, and
`record.infrastructure_failure` filled in. `bzbench/record.py` gained the
infrastructure terminations and the `NON_CHESS_TERMINATIONS` set.

**Why.** An authentication failure, a rate limit or a dropped connection is not
a chess outcome. Before this change the only way for an adapter to stop a game
was `AbortGame`, which records an operator abort and would have mislabelled
every provider failure.

**What did not change.** The chess rules. An illegal move and a malformed
response are still an immediate loss with no retry and no repair, and
resignation is still a loss. Nothing that was a loss became a non result.

## Additions that change no existing behaviour

* `bzbench/adapters/openai_api.py`, registered as the `openai` adapter.
* `bzbench/pricing.py` and `pricing/gpt-6-astra.json`.
* `AIPlayer.pop_turn_metadata()` and `AIPlayer.session_summary()`, both
  returning `None` in the base class, so the manual adapter is untouched.
* `TurnRecord.api`, `GameRecord.api`, `GameRecord.infrastructure_failure`. All
  optional and `None` for a manual game.
* API configuration fields on `MatchConfig`, all with defaults, ignored by the
  manual adapter.
* The `preflight` command and the API options on `play`.
* Cost and token columns in `summarize`.

## Verification

`python3 -m pytest -q` covers the frozen behaviour and the new behaviour in one
suite. The frozen guarantees are asserted by `tests/test_protocol_leakage.py`,
`tests/test_referee.py` and `tests/test_record_and_stats.py`, none of which were
weakened; the only edit to an existing test was in
`tests/test_manual_adapter.py`, where a registry test used `openai` as its
example of an unknown adapter name and now uses `anthropic`.
