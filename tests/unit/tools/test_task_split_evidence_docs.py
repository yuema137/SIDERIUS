"""Keep #225's single split-evidence obligation reachable from task onboarding.

Only this guard owns loss of the canonical section or either inbound link:
the general Markdown link guard ignores fragments and cannot notice a deleted
link. Removing the heading or an inbound target fails its named assertion.
This checks documentation structure, never scientific leakage or prose meaning.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL = "docs/guides/define-a-task.md"
INBOUND = {
    "docs/guides/bring-your-own-split.md": "define-a-task.md",
    "docs/concepts/task-package.md": "../guides/define-a-task.md",
}


def _assert_split_evidence_reachable(documents: dict[str, str]) -> None:
    assert "## Required task-owned split evidence" in documents[CANONICAL].splitlines(), (
        f"{CANONICAL}: missing required split-evidence section"
    )
    for source, target in INBOUND.items():
        assert f"]({target}#required-task-owned-split-evidence)" in documents[source], (
            f"{source}: missing link to the canonical split-evidence section"
        )


def test_task_split_evidence_is_present_and_reachable() -> None:
    documents = {
        name: (REPO_ROOT / name).read_text(encoding="utf-8") for name in (CANONICAL, *INBOUND)
    }
    _assert_split_evidence_reachable(documents)
