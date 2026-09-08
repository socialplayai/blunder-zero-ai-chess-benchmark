# Three dimensions, never collapsed into one number

API-PILOT-v0.1 game 2 is the reason this document exists. In that game Astra was
simultaneously:

* playing excellent chess in the sampled move sequence (ACPL 20.4, accuracy
  94.07%, one inaccuracy in 22 moves),
* winning materially by more than a rook,
* formatting every response perfectly as a bare SAN token,
* and unreliable enough to lose the game by inventing a move through an
  occupied square.

All four are true at once. A single "model strength" number would hide three of
them. Every report from here on separates the following.

## 1. Chess quality

What the model chose, given that it was able to choose legally.

* average centipawn loss
* accuracy
* inaccuracies, mistakes, blunders
* the result **conditional on legal play**, stated separately from the result
* the position evaluation at the point any non chess termination occurred, so a
  truncated game is not silently read as a chess loss

## 2. Protocol reliability

Whether the interface worked at all.

* legal responses over total responses
* malformed responses: not a single SAN token (prose, markdown, UCI, multiple
  moves, empty)
* state tracking failures: a well formed SAN move that is not legal in the
  position, which is the signature of the model losing the board
* the ply and position at which any failure occurred
* retries

Malformed and state tracking failures are different findings. The first is an
output discipline problem and is fixable with prompting. The second is a model
of the board problem and is the thing the RAW protocol is designed to measure.

## 3. Operational performance

Whether it is practical.

* latency per move, median and maximum
* input, cached input, output and reasoning tokens
* cost per move and per game
* infrastructure incidents: retries, rate limits, timeouts, truncations

## Reading the numbers honestly

**Do not convert a small number of failures into a rate and then compound it.**
One legality failure in 54 responses is one failure in 54 responses. Treating
1.85% as a per move probability and deriving "about half of 40 move games would
fail" is an illustrative compounding example only. Failures are very likely
position dependent rather than independent, and a single event supports no
reliability estimate at all.

**Accuracy is not comparable across game lengths or across positions.** The
Lichess model flatters a player who is already lost, and a game truncated at
move 23 samples a different distribution of positions than a game that reached
move 31.

**A non chess termination is not a chess result.** `illegal_move` is a chess
result under the frozen rules and is scored as a loss. `api_*`,
`cost_limit_abort`, `token_limit_abort` and `aborted` are not, and they leave
the result as `*`.
