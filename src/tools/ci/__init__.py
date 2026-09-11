"""CI parity harness.

Three authorities cooperate and must never merge (docs/testing/ci_parity.md §1):

    tools.ci_selection   WHAT should run   (existing, unchanged)
    tools.ci             HOW it runs reproducibly, and WHY results diverged

This package owns execution-root preflight and run provenance. It does NOT
map changed files to tests — that is ``tools.ci_selection``'s sole
responsibility, and duplicating it would create a second authority.
"""
