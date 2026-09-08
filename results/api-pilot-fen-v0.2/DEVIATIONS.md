# API-PILOT-FEN-v0.2 deviations

**None affecting the games.**

* execution commit `7658bcb1e4447844adf64d0d98459475875f74ab`, frozen before the
  first API call and verified against HEAD immediately before each game;
* no commit was made to the repository between the two games;
* both records carry `environment.bzbench_commit =` `7658bcb...`;
* fresh conversation per game, no response id shared with any earlier game, no
  resumed conversation;
* no diagnostic ran while a scored game was running.

## Amendment A1 was written during the pair

The draw branch (`docs/api-pilot-fen-v0.2.md`, Amendment A1) was written at
2026-09-08T07:47:22Z, while game 2 was still playing. That is a mid experiment
amendment, so the evidence that it was blind to the result is recorded in the
amendment itself: the game 2 process was alive and unterminated, its `game.json`
did not exist, its log held only the 434 byte launch banner, and nothing was
committed during the pair. The amendment governs what happens after a pair, not
how a game is scored, and game 2 finished as a win, so the branch it added was
not the branch taken.
