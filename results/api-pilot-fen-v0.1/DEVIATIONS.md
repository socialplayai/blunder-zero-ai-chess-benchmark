# API-PILOT-FEN-v0.1 deviations

**None.**

The correction adopted after API-PILOT-v0.1 deviation D1 was applied and held:

* execution commit `502ea8b8ec0a9890976ffbacf70ca310fd548f34`, frozen before the
  first API call;
* HEAD was checked against that commit immediately before each game;
* no commit was made to the repository between the two games;
* both game records carry `environment.bzbench_commit =` `502ea8b...`, which can
  be read back from `game-001/game.json` and `game-002/game.json`;
* neither game shared a conversation with the other, with the RAW pilot, or with
  any diagnostic probe. No response id appears in more than one record.

The diagnostic probes were run outside the pair: the fresh arms before game 1 was
launched, the chain arms after game 2 closed. Nothing ran concurrently with a
scored game.
