# API-PILOT-v0.1 deviations

Recorded because a deviation that is disclosed is evidence, and a deviation that
is quietly repaired is not.

## D1: game 2 ran at a different commit than the preregistration named

**Preregistered execution commit:** `0779f6b43d351ad85c599ae4f49d5a83b0b28eef`

**Game 1 ran at:** `0779f6b` (as preregistered)

**Game 2 ran at:** `b80618ba76be6d588b8c04443416963b65aac27c`

**Cause.** Between the two games a housekeeping commit was made that moved a
mock rehearsal record out of `games/` and filed a summary file. Game 2 was then
launched from the updated HEAD instead of from the frozen commit. Operator
error, not a code change.

**What differs between the two commits**

```
$ git diff --stat 0779f6b b80618b
 .gitignore                          |  1 +
 docs/results/api-pilot-v0.1-g1.json | 65 +++++++++++++++++++++++++++++++++++++
```

**What is identical**

```
$ git rev-parse 0779f6b:bzbench  b80618b:bzbench
fdced27fa87f8fcc1830d6fcfc898588fde9296f
fdced27fa87f8fcc1830d6fcfc898588fde9296f

$ git rev-parse 0779f6b:pricing  b80618b:pricing
6cb07efb6c39a325c938fcfd73afb3527590ec43
6cb07efb6c39a325c938fcfd73afb3527590ec43
```

The benchmark code tree and the pricing tree are byte identical at both commits.
The referee, the protocol builder, the SAN validation, the adapter, the engine
wrapper and the rates Game 2 was scored with are the same objects that Game 1
used.

**Ruling.** Substantively comparable, procedurally deviant. Game 2 stays in the
pilot and is not re-run. Re-running an observed failure until the bookkeeping
looks tidier would produce a replacement result that a reader could reasonably
read as cherry picking, which is a worse problem than the deviation itself.

**Correction applied going forward.** No commit is made to this repository
between the games of a frozen pair. The runner HEAD is checked against the
preregistered commit before each game of an experiment.
