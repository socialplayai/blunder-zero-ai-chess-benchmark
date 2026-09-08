# The OpenAI Responses API adapter

This document is the specification of how GPT-6 Astra plays in this benchmark
and of every policy that could otherwise be mistaken for a chess result.

## What the model gets

One request per move, built entirely by `_build_request`:

```json
{
  "model": "gpt-6-astra",
  "input": "<the benchmark prompt, verbatim>",
  "reasoning": {"effort": "high"},
  "tools": [],
  "store": true,
  "previous_response_id": "resp_...",
  "metadata": {"benchmark": "...", "game_id": "...", "ply": "6", "protocol": "raw"}
}
```

That is the complete request. There is no `tool_choice`, no `functions`, no
`response_format` or structured output schema, no `include`, no
`parallel_tool_calls`, no `instructions` field, and no system message the
benchmark did not build. `tools` is an empty list on every call, which is
asserted by the test suite for every request of a full game.

`input` is byte identical to the prompt the protocol layer produced, which is
the same prompt the manual adapter would have printed for an operator to paste.
The API path and the manual path therefore differ in transport only.

Output discipline is part of the benchmark: the prompt asks for one SAN move and
nothing else, and nothing in the request forces that. A model that answers with
prose fails the benchmark rather than being corrected by a schema.

## Conversation state

One game is one response chain. The first request of a game has no
`previous_response_id`; every later request carries the id of the previous
response, with `store=true`, which is what lets Astra keep its own earlier
reasoning. A fresh adapter instance is built per game, so no state crosses a
game boundary. Every response id is recorded, so a run can be traced in the
provider's logs without storing any content twice.

`--no-store` is available for a zero retention run. It also removes cross turn
reasoning continuity, so it changes the experiment and must be reported if used.

## Reasoning effort

Levels accepted by the Responses API: `none`, `minimal`, `low`, `medium`,
`high`, `xhigh`, `max`. `gpt-6-astra` rejects `none` with HTTP 400, so the
adapter rejects it locally before any request is sent.

An unsupported level raises `ReasoningEffortNotSupported` at construction time.
The adapter never substitutes a different level. The requested and the effective
level are both recorded, per move and per game.

## Failure taxonomy

Nine outcomes, and only three of them are chess results.

| Outcome | Termination | Chess result |
| --- | --- | --- |
| Illegal move | `illegal_move` | loss |
| Malformed response | `illegal_move` | loss |
| Resignation | `resignation` | loss |
| API authentication or permission failure | `api_authentication` | none, `*` |
| Rate limit, retries exhausted | `api_rate_limit` | none, `*` |
| Timeout, retries exhausted | `api_timeout` | none, `*` |
| Network or connection failure | `api_network` | none, `*` |
| Provider 5xx | `api_server_error` | none, `*` |
| Rejected request, 4xx that is our fault | `api_request_rejected` | none, `*` |
| Response truncated at `max_output_tokens` | `api_output_limit` | none, `*` |
| Incomplete response, any other reason | `infrastructure_error` | none, `*` |
| Spend guard reached | `cost_limit_abort` | none, `*` |
| Token guard reached | `token_limit_abort` | none, `*` |
| Operator abort | `aborted` | none, `*` |

Every infrastructure termination leaves `result` as `*` and `ai_outcome` as
`unfinished`, and `record.infrastructure_failure` carries the kind, the scrubbed
message and the attempt log. `NON_CHESS_TERMINATIONS` in `bzbench/record.py` is
the machine readable version of that rule.

An incomplete response is treated as infrastructure rather than as a bad move,
because it is caused by a cap the operator set or by a provider stop, not by the
model's chess. When the provider reports `incomplete_details.reason ==
"max_output_tokens"` the termination is the more specific `api_output_limit`, so
a run that keeps hitting the ceiling is visible in the summary rather than
hidden among generic failures.

## The output ceiling

`--max-output-tokens` sets the Responses API `max_output_tokens` parameter,
which bounds the tokens one response may produce. Reasoning tokens count
against it, because the API bills and counts reasoning as output.

The ceiling is a preregistered constant. It is sent on every request of a game,
it is recorded in the game configuration and in `record.api.max_output_tokens`,
and nothing in the adapter lowers it in response to the position, the move
number or the accumulated spend. A truncated response is never retried and never
scored: the game ends as `api_output_limit` with no result.

Unset by default. API-PILOT-v0.1 sets it to 12,000.

## Retry policy

Exactly one rule decides whether a retry is allowed: **was there a model
response?**

* No response yet, and the failure is transient (`RateLimitError`,
  `APITimeoutError`, `APIConnectionError`, 5xx): retry, up to `--max-attempts`
  total attempts, default 3, with exponential backoff from `--backoff-seconds`
  (default 5s: 5s, 10s, ...) plus jitter.
* No response yet, and the failure is not transient (401, 403, 400, unknown
  model): no retry.
* A response exists: never retried, whatever it contains. An empty string, a
  paragraph of analysis or an illegal move all go to the referee as they are.

The SDK client is constructed with `max_retries=0` so that the SDK cannot retry
behind the adapter's back. Every attempt is appended to `turn.api.attempts` with
its error kind, status code, request id and elapsed time. A retry resends a byte
identical request, so retrying cannot put more chess information in front of the
model.

## Cost accounting

Rates live in `pricing/gpt-6-astra.json`, never in code, with the verification
timestamp and the official source URL. `bzbench/pricing.py` computes:

```
input_cost  = (input_tokens - cached_tokens) * input_rate + cached_tokens * cached_rate
output_cost = output_tokens * output_rate
total       = input_cost + output_cost
```

`usage.output_tokens` already includes
`usage.output_tokens_details.reasoning_tokens`, so reasoning is charged exactly
once, inside `output_cost`. The reasoning share is reported separately as
`reasoning_cost_share_usd` and flagged `reasoning_included_in_output_cost`, for
information only. Fields the API does not return stay `null`; reasoning token
counts are never inferred.

Requests whose input exceeds 272,000 tokens are charged at the long context
rates, which the record marks per move.

Known limitation: the pricing page lists a separate cache write rate, but the
API does not expose a cache write token count, so it is recorded in the pricing
file and excluded from the computed cost. A computed total is therefore a lower
bound whenever the provider writes new cache entries. The raw usage object is
stored per move so any figure can be recomputed later.

## Spend guards

`--max-cost-usd` (default $15 per game) and `--max-total-tokens` are checked
*before* every request. When a guard is already met the game ends as
`cost_limit_abort` or `token_limit_abort` with no chess result, and no further
request is sent.

### What the guard is, and what it is not

It is a **metered usage guard on the usage the API reports**, not a billing
ceiling. Three separate reasons, all of them stated here rather than discovered
later:

1. **Single call overshoot.** The check runs before a request, so the request
   that crosses the cap still completes and is still billed. The overshoot is
   bounded, not zero. With an output ceiling of 12,000 tokens at $50 per Mtok
   the output side of one more call is at most **$0.60**. The input side is
   bounded only by what is sent: at 20,000 input tokens it is $0.20, and at the
   272,000 token short context threshold it is $2.72. So for the pilot
   configuration a realistic single call bound is **under $1**, and a
   pathological one is about **$3.32**. `record.api.max_single_call_exposure`
   stores this calculation per game, using the largest input actually observed.
2. **Cache writes are not observable.** The pricing page lists a separate cache
   write rate, and the usage object exposes no cache write token count, so no
   figure computed here can include it. Every computed total is a lower bound.
3. **Nothing here reads the provider's billing.** The numbers come from the
   usage objects of this run only.

The honest summary: a $25 guard means this benchmark stops issuing requests once
it has metered $25 of usage, with a bounded overshoot of roughly one more call.
It does not mean the invoice cannot exceed $25. Use provider side budget alerts
if a hard financial limit is required.

## Secrets

The key is read from `OPENAI_API_KEY` and from nowhere else. It is never written
to a record, a PGN, a log line or a prompt, and never included in `describe()`,
which stores the variable *name* only. Every error string that could contain a
key passes through `scrub_secrets`, which removes `sk-` shaped tokens and any
exact match of the environment value. Tests assert the key cannot reach
`game.json`, `game.pgn`, stdout or stderr.
