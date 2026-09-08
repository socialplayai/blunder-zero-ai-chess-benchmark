"""Corpus amendment C2: name the chain parent explicitly.

The defect C2 corrects: the corpus stored each position's **own**
`response_id`, and the runner branched chain arms from it, so the conversation
being continued already contained the answer to the very prompt being asked. The
chain arms returned six tokens with zero reasoning and echoed the played move.

C2 adds two fields to every existing position and changes nothing else:

* `chain_from_response_id`: the response id of the **immediately preceding model
  turn** in the same source game;
* `chain_from_ply`: the ply of that preceding model response.

No position is added, removed, resampled or reordered. Keys, source games,
protocol assignment, depth strata, colour balance, the Stage 1 ordering and the
seed are all untouched.

    python3 tools/amend_corpus_c2.py --corpus <corpus.json>
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bzbench.record import GameRecord  # noqa: E402


def model_turns(record: GameRecord) -> list:
    return [t for t in record.turns
            if t.actor == "ai" and (t.api or {}).get("response_id")]


def parent_of(record: GameRecord, ply: int) -> tuple[int, str]:
    """The model turn immediately preceding `ply` in the same game."""
    turns = model_turns(record)
    index = next(i for i, t in enumerate(turns) if t.ply == ply)
    if index == 0:
        raise SystemExit(f"ply {ply} is the first model turn; it has no parent")
    parent = turns[index - 1]
    sampled = turns[index]
    # Cross check against what the game itself recorded as the chain link.
    recorded = (sampled.api or {}).get("previous_response_id")
    parent_id = (parent.api or {})["response_id"]
    if recorded != parent_id:
        raise SystemExit(
            f"chain link mismatch at ply {ply}: the sampled turn recorded "
            f"previous_response_id {recorded!r} but the preceding model turn is "
            f"{parent_id!r}"
        )
    return parent.ply, parent_id


def amend(corpus: dict) -> dict:
    records: dict[str, GameRecord] = {}
    positions = []
    for position in corpus["positions"]:
        path = REPO / position["source_path"]
        record = records.setdefault(str(path), GameRecord.load(path))
        parent_ply, parent_id = parent_of(record, position["ply"])
        if parent_id == position["response_id"]:  # pragma: no cover - impossible
            raise SystemExit("parent id equals the sampled id")
        positions.append({**position,
                          "chain_from_ply": parent_ply,
                          "chain_from_response_id": parent_id})
    amended = {**corpus, "positions": positions}
    amended["amendments"] = corpus.get("amendments", []) + [
        {
            "id": "C2",
            "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(
                timespec="seconds"),
            "summary": (
                "added chain_from_response_id and chain_from_ply, the "
                "immediately preceding model turn, so chain arms branch from "
                "before the sampled turn instead of from the sampled turn itself"
            ),
            "positions_changed": 0,
            "fields_added": ["chain_from_response_id", "chain_from_ply"],
            "corpus_sha256_before": hashlib.sha256(
                (json.dumps(corpus, indent=2) + "\n").encode()).hexdigest(),
        }
    ]
    return amended


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True)
    args = parser.parse_args()
    path = pathlib.Path(args.corpus)
    corpus = json.loads(path.read_text())
    if any(a["id"] == "C2" for a in corpus.get("amendments", [])):
        print("C2 is already applied", file=sys.stderr)
        return 2
    amended = amend(corpus)
    payload = json.dumps(amended, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (path.parent / "CORPUS.sha256").write_text(f"{digest}  {path.name}\n")
    print(f"C2 applied to {len(amended['positions'])} positions")
    print(f"  corpus sha256 before {amended['amendments'][-1]['corpus_sha256_before']}")
    print(f"  corpus sha256 after  {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
