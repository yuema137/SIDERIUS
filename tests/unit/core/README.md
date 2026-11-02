# tests/unit/core

Core tests protect admission, verification, identity, persistence, resume, and
hardware-authority invariants with synthetic schemas and subprocess seams.

## Source and route

`.venv/bin/python -m pytest tests/unit/core/test_adaptive_verification.py -q`

Owner: `src/core/`; this route is deterministic and does not run GPU training.
The nested `fixtures/step00_replay_workspace/` tree is retained by replay and
provenance tests as a static workspace shape; it is not a runnable campaign.

Storage-budget tests use a controlled clock and real startup receipts. For
example, publishing authorization at time 90 starts a new 600-second
acknowledgment window: consumption at 650 is valid, while 690 is too late.
Run the focused witness from the repository root with the development
environment installed:

```bash
.venv/bin/python -m pytest tests/unit/core/test_offline_storage_budget.py -q
```

Both cases should pass without waiting for those intervals in real time. The
[launch testing contract](native-launch-testing.md) explains how this differs
from real-process tests on slow storage.
