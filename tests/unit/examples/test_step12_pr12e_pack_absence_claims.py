"""Step 12 / PR-12e — a pack must not deny what it ships (issue #267).

ONE property, and nothing else: **no example pack's user-facing prose asserts
the ABSENCE of an artifact the pack now ships.**

This is the defect issue #267 was filed for, and it was live on landed master
in two places at once. `examples/davis_future_prediction/README.md` said *"No
clip manifest exists in this pack — deliberately"* while
`data/manifests/clips.csv` (600 clips, digest pinned in `SHA256SUMS`) had
shipped since D14-3 and `STATUS.md` said so on the same day. The Pets pack
carried the twin of it for `quickstart.sh`. Both survived several doc-sync
passes because a "by design" absence line reads as true forever: nobody
re-derives it, and the artifact that falsifies it lands in a different file.

Why nothing else catches it. Pydantic, ruff and pyright do not read Markdown.
`test_pack_governance.py` asserts what a pack MUST contain, never that its
prose agrees with what it contains. The per-pack quickstart modules drive the
published command; a stale sentence three sections away leaves them green.

**Deliberately not a documentation linter.** The vocabulary is a frozen
two-row table, not a grammar: each row pairs one absence phrase with the one
repo-relative path that falsifies it. Historical corrections are excluded by a
single mechanical rule — a claim someone is QUOTING in order to retract it is
inside quotation marks, and quoted spans are removed before the search. That
is what lets the D-FINAL correction paragraphs (which necessarily restate the
false lines) stay green while a live claim goes red.

Portability: the checkout root is derived from ``__file__``; no absolute
repository path is written down.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = REPO_ROOT / "examples"

#: The user-facing prose of a pack. `PROVENANCE.md` is excluded: it records
#: upstream distribution facts, not claims about what this pack contains.
CLAIM_DOCS = ("README.md", "STATUS.md")

#: The frozen vocabulary. Each row is (absence phrase, the ONE repo-relative
#: path inside the pack whose existence makes the phrase false). Lowercase —
#: the search is case-insensitive.
ABSENCE_CLAIMS: tuple[tuple[str, str], ...] = (
    ("no launcher", "quickstart.sh"),
    ("no clip manifest", "data/manifests/clips.csv"),
)

#: Spans a writer is quoting rather than asserting. A retraction has to restate
#: the false line, so without this every correction paragraph would be its own
#: violation.
_QUOTED_SPAN = re.compile(r'"[^"]*"')


def _pack_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "STATUS.md").is_file())


def _asserted_prose(text: str) -> str:
    """`text` with quoted spans removed, whitespace-flattened and lowercased.

    Flattening matters: these documents wrap at ~76 columns, so a claim such as
    "no clip\\nmanifest" is one phrase to a reader and two tokens to `str.find`.
    """
    return " ".join(_QUOTED_SPAN.sub(" ", text).split()).lower()


def _contradictions(pack: Path) -> list[str]:
    """Every (doc, phrase) where the pack denies something it ships."""
    found: list[str] = []
    for doc in CLAIM_DOCS:
        path = pack / doc
        if not path.is_file():
            continue
        prose = _asserted_prose(path.read_text(encoding="utf-8"))
        for phrase, relpath in ABSENCE_CLAIMS:
            if phrase in prose and (pack / relpath).exists():
                found.append(f"{pack.name}/{doc} claims {phrase!r} but ships {relpath}")
    return found


def test_no_pack_denies_an_artifact_it_ships() -> None:
    """Defect caught: a pack keeps a "by design" absence line after the thing it
    denies has landed — issue #267's exact shape, twice on landed master.

    How it fails: every offending (pack, document, phrase, shipped path) is
    reported by name, so the fix is to edit that sentence, not to hunt for it.
    """
    packs = _pack_dirs(EXAMPLES_ROOT)
    assert packs, "no example packs found"
    offenders = [item for pack in packs for item in _contradictions(pack)]
    assert offenders == [], "\n".join(offenders)


def test_every_frozen_claim_row_is_live_somewhere() -> None:
    """Defect caught: the guard above passes VACUOUSLY because no pack ships the
    artifact a row names any more (renamed `quickstart.sh`, deleted
    `clips.csv`), so the phrase could be reintroduced unnoticed.

    How it fails: a row whose path exists in no pack is reported. This is the
    reachability half — without it, deleting the artifact silently retires the
    rule instead of failing it.
    """
    dead = [
        f"{phrase!r} -> {relpath} exists in no pack"
        for phrase, relpath in ABSENCE_CLAIMS
        if not any((pack / relpath).exists() for pack in _pack_dirs(EXAMPLES_ROOT))
    ]
    assert dead == [], "\n".join(dead)


@pytest.mark.parametrize(
    ("prose", "expected_offenders"),
    [
        ("Not in this pack, by design: no launcher, no cache.", 1),
        ('This line used to say "no launcher", which became false.', 0),
        ('It claimed "no clip\nmanifest, no loader, no launcher". All false.', 0),
        ("The adapter is deliberately not a launcher.", 0),
    ],
    ids=["live-claim", "quoted-retraction", "quoted-across-a-line-wrap", "not-a-claim"],
)
def test_the_detector_separates_a_live_claim_from_a_quoted_retraction(
    tmp_path: Path, prose: str, expected_offenders: int
) -> None:
    """Proves the guard is neither blind nor trigger-happy, on a mirror pack.

    Defect caught, in both directions: a detector that ignored quoting would
    fire on every D-FINAL correction paragraph and be switched off; one that
    matched only whole lines would miss a claim broken across a Markdown wrap,
    which is how these documents are actually written.

    How it fails: the offender count for the mirror pack differs from the
    hardcoded expectation for that input class.
    """
    pack = tmp_path / "examples" / "mirror_pack"
    pack.mkdir(parents=True)
    (pack / "quickstart.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (pack / "STATUS.md").write_text(f"# STATUS\n\nL4.\n\n{prose}\n", encoding="utf-8")

    assert len(_contradictions(pack)) == expected_offenders
