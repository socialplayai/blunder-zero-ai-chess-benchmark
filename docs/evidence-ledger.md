# Evidence ledger

The narrow record of what has actually been shown, kept deliberately smaller
than what the numbers tempt you to say. Anything not written here has not been
established.

Last updated after the complete programme: all six FEN ladder games, the RAW
pilot pair, the ply 45 diagnostic and RELIABILITY-STUDY-v0.1.

**A note on the word strength.** The opponent is Stockfish 18 with
`UCI_LimitStrength` enabled at a fixed 200,000 node budget. Those are **limiter
settings, not human Elo ratings**, and a limited engine does not play like a
human of the nominal rating. Everything below says *limiter setting* or *rung*
for that reason, and no statement here converts a result into a rating of the
model.

## Established

**Astra can play chess through the RAW protocol.** It tracked full games from
move history alone and produced well formed SAN on every response of every game
so far. 115 responses, 115 correctly formatted bare SAN tokens, 0 malformed.

**In the six game FEN ladder, Astra won both games at the Stockfish limiter
settings 1320 and 1500, then lost both games at 1700.** Six games, one per
colour at each of three rungs, 329 legal responses out of 329. Under RAW at the
1320 setting it won as White and lost as Black on an illegal move, not on chess.

That sentence is the whole strength result, and it is deliberately not
compressed further. **Not established: any bracket, band or estimate of the
model's rating.** Two games per rung cannot separate a real strength boundary
from the variance of two games, and the opponent is a limiter setting rather
than a rated player, so there is no scale to place the model on.

**Measured move quality degraded monotonically as the limiter rose**, ACPL 13.4
and 11.0 at 1320, 35.0 and 30.4 at 1500, 56.7 and 32.1 at 1700, and at the 1700
rung the engine posted the better ACPL for the first time. Six games do not make
that a trend; it is the shape the data has.

**Cumulative input token volume is structurally approximately quadratic in the
number of responses** under full history resend, which is a property of the
transport and not a measurement. The 186 ply game sent 6.03M input tokens across
93 turns, 252 on the first and 140,768 on the last, and cost $11.50. Whether
total dollar cost follows the same curve depends on output behaviour, caching and
transcript growth, so the quadratic claim is made about input volume only.

**One illegal move response has been observed in scored play**, at ply 45 of
API-PILOT-v0.1 game 2, from a winning position, under RAW.

**Legality counts, stated as counts.**

| Set | Legal responses | Illegal | Malformed |
| --- | --- | --- | --- |
| RAW pair, 1320 setting | 53/54 | 1 | 0 |
| FEN pair, 1320 setting | 61/61 | 0 | 0 |
| FEN pair, 1500 setting | 138/138 | 0 | 0 |
| FEN pair, 1700 setting | 130/130 | 0 | 0 |
| **FEN programme total** | **329/329** | **0** | **0** |
| RELIABILITY-STUDY-v0.1 | 159/160 | 1 | 0 |
| ply 45 diagnostic, 4 arms | 19/20 | 1 | 0 |

**No causal mechanism for the illegal move has been established.** The
diagnostic put the exact position back in front of the model twenty times. The
only reproduction of `Qh5+` came from the chain FEN arm, with the authoritative
position in the prompt. RAW produced ten legal answers out of ten.

## Explicitly not established

**That FEN is more reliable than RAW.** One failure in 54 against zero in 61 is
what chance looks like at this sample size. Fisher exact, two sided:
**p = 0.47**.

**That FEN is reliable.** Zero failures in 61 responses gives an exact 95%
confidence interval of **[0, 5.9%]** for the underlying per response failure
rate, and the one sided rule of three puts it at up to **4.9%**. A 4% failure
rate would still lose most long games and is entirely consistent with what has
been seen.

**That RAW's failure rate is 1.85%.** The exact 95% interval for 1 in 54 is
**[0.05%, 9.9%]**. Pooling all scored play, 1 in 115, gives **[0.02%, 4.8%]**.

**That any of these responses are independent.** Responses inside a game share a
position sequence, an opponent, an opening and a conversation. Treating 54
responses from two games as 54 independent trials overstates the information by
an unknown factor. Future reliability work clusters by position and game.

**That FEN improves chess quality.** The FEN pair posted lower ACPL (13.4 and
11.0 against 27.9 and 20.4) while facing *better* opponent play (Stockfish ACPL
41.0 and 45.8 against 58.0 and 54.0), which is intriguing and is exactly why it
is not a conclusion from four games across four different openings. It is
tracked as a descriptive column.

**That RAW costs more reasoning.** The 8,761 against 6,632 reasoning token
difference in the fresh arms is five trials per cell on one position.

## The reliability study, completed

**RELIABILITY-STUDY-v0.1 ran 160 preregistered responses across four conditions
and stopped under its own futility rule.** 159 were legal and well formed; one
was not. The rule, fixed before execution, specified that 0 to 2 illegal
responses would end the study without a comparison between conditions. It fired,
Stage 2 was never run, and **no condition is claimed to be more or less reliable
than another**.

The finding is about the instrument: illegal move events are too rare, in these
positions and at this sample size, to discriminate the conditions the study was
built to compare. That says nothing about model reliability in general and
nothing about domains other than chess legality.

## Protocol policy, adopted after the FEN pair

The two protocols answer different questions and are no longer mixed in one
programme.

* **FEN is the primary protocol for measuring chess strength.** Reconstructing
  the board from conversation history is an extra task, and when it fails it
  makes a single event simultaneously a chess result and a memory result. The
  strength ladder runs under FEN.
* **RAW is a separate capability and reliability benchmark.** The question it
  answers, whether the model can hold a board across a conversation, is worth
  measuring on its own terms and not as a tax on every strength measurement.

Both protocols remain frozen and unchanged. Nothing about how a game is scored
has changed; only which protocol the strength programme uses.
