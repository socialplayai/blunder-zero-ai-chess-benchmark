# API-PILOT-FEN-v0.3 deviations

**None.**

* execution commit `64818abdc392e724fe0f64ebfd557767d661e8ed`, frozen before the
  first API call and verified against HEAD before each game;
* no commit was made to the repository between the two games;
* both records carry `environment.bzbench_commit =` `64818ab...`;
* fresh conversation per game, no response id shared with any earlier game;
* no diagnostic ran while a scored game was running;
* the Track 2 corpus was frozen before this rung began and contains no 1700
  position.

Operational amendment O1, the per game spend guard from $25 to $50, was recorded
in the frozen protocol before the pair and is visible in both records as
`config.max_cost_usd = 50.0`. Neither game came close: $1.65 and $6.65.
