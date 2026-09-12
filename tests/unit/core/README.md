# tests/unit/core

Core tests protect admission, verification, identity, persistence, resume, and
hardware-authority invariants with synthetic schemas and subprocess seams.

## Source and route

`.venv/bin/python -m pytest tests/unit/core/test_adaptive_verification.py -q`

Owner: `src/core/`; this route is deterministic and does not run GPU training.
The nested `fixtures/step00_replay_workspace/` tree is retained by replay and
provenance tests as a static workspace shape; it is not a runnable campaign.
