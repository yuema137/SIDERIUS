"""Stage-3 writers for the Gold campaign (``docs/campaign/stage_artifact_contract.md``).

The package holds the ONE shared compose-and-score module
(:mod:`scripts.stage3.stage3_common`) and the per-writer entrypoints that
call it. No module in this package computes scoring arithmetic of its own —
the frozen TIDMAD score formula lives in ``execute_tools.scoring_utils`` and
is invoked exactly once per composition, over the full 0..19 file set.
"""
