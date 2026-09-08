"""Closure invariant: a clean git status is not proof that artifacts are tracked.

The `.gitignore` rule `diagnostics/` was unanchored, so it also matched
`results/diagnostics/`. Every published diagnostic artifact was silently excluded
from git for several commits while `git status --porcelain` reported zero lines,
because ignored files do not appear there. The corpus was frozen and hash
verified on disk the whole time, so no result changed, but the repository looked
complete when it was not.

The invariant that would have caught it, and that every future experiment closure
should run: **assert the expected artifact paths are tracked**, then verify their
manifest digests. Absence of noise is not evidence of presence.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

PUBLISHED_TREES = [
    "results/api-pilot-v0.1",
    "results/api-pilot-fen-v0.1",
    "results/api-pilot-fen-v0.2",
    "results/api-pilot-fen-v0.3",
    "results/diagnostics/api-pilot-v0.1-g2-ply45",
    "results/diagnostics/reliability-study-v0.1",
]

WORKING_TREES_THAT_MUST_STAY_UNTRACKED = ["games", "rehearsals", "diagnostics"]


def tracked(path: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", path], cwd=REPO,
                         capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if line.strip()]


@pytest.mark.parametrize("tree", PUBLISHED_TREES)
def test_every_published_tree_is_actually_tracked(tree):
    on_disk = [p for p in (REPO / tree).rglob("*") if p.is_file()]
    if not on_disk:
        pytest.skip(f"{tree} not present in this checkout")
    in_git = tracked(tree)
    assert in_git, f"{tree} exists on disk but nothing under it is tracked"
    assert len(in_git) == len(on_disk), (
        f"{tree}: {len(on_disk)} files on disk, {len(in_git)} tracked"
    )


@pytest.mark.parametrize("tree", PUBLISHED_TREES)
def test_no_published_path_is_ignored(tree):
    """The specific failure mode: an ignore rule silently swallowing evidence."""
    result = subprocess.run(["git", "check-ignore", "-v", tree],
                            cwd=REPO, capture_output=True, text=True)
    assert result.returncode != 0, (
        f"{tree} is matched by an ignore rule: {result.stdout.strip()}"
    )


@pytest.mark.parametrize("tree", WORKING_TREES_THAT_MUST_STAY_UNTRACKED)
def test_working_output_stays_out_of_git(tree):
    assert tracked(tree) == [], f"{tree} is working output and must not be tracked"


def test_every_manifest_verifies():
    checked = 0
    for manifest_path in (REPO / "results").rglob("MANIFEST.json"):
        manifest = json.loads(manifest_path.read_text())
        for name, entry in (manifest.get("artifacts") or {}).items():
            target = manifest_path.parent / name
            assert target.exists(), f"{manifest_path}: missing artifact {name}"
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            assert digest == entry["sha256"], f"{manifest_path}: {name} digest drift"
            checked += 1
    assert checked >= 8, "expected several hashed artifacts across the manifests"


def test_the_publication_tag_points_at_a_real_commit():
    result = subprocess.run(
        ["git", "rev-parse", "astra-chess-benchmark-v0.1^{commit}"],
        cwd=REPO, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip("publication tag not present in this checkout")
    commit = result.stdout.strip()
    assert len(commit) == 40
    # The tag must contain the study results, not merely precede them.
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit,
         "results/diagnostics/reliability-study-v0.1"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout
    assert "RESULTS.md" in listed
    assert "responses-stage1.jsonl" in listed
    assert "responses-stage2" not in listed, "Stage 2 was never run"
