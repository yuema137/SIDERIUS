# tests/unit/sdsc_submission_scripts

Submission-script tests statically pin launch flags, workspace/data-dir
portability, manifest identity, and gate/termination wiring. They use inert
argv and temporary paths, not an SDSC submission.

## Focused route

`.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/test_arxiv_261_launch_wiring.py -q`

Owner: `src/workflows/run_one_iteration.py`, `scripts/launch/`, and
`scripts/slurm/`; see the [unit map](../README.md).
