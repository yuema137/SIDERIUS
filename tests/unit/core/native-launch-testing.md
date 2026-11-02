# Native launch wiring witnesses

`test_native_gpu_execution.py` owns CPU-only witnesses for selected native
training/inference execution, admission, authorization, and terminal receipts.
Scientific children and GPU facts are synthetic; the executor, subprocess
supervisor, observer state machine, and receipt persistence remain real.

The launch matrix injects fixed clocks into the observer and inference startup
objects through their existing constructor interfaces. Each anchor uses the
current monotonic time domain (the observer uses its initial observation's
completion), so authorization publication remains comparable to the measurement
allowance and watchdog. This matrix verifies wiring, not elapsed-time policy.
It must not increase runtime policy deadlines to accommodate host scheduling.

Both synthetic children wait on a FIFO before exiting. The parent releases it
only after `protection_receipt().valid_live_samples` is nonzero: returning from
the sampler alone is insufficient because the observer checks child liveness
again before committing a sample. Inference publishes its consumption receipt
before waiting, so the witness can force ACK consumption to precede sampling.
The barrier's 600-second escape bounds a broken test handshake and fails the
test; it does not authorize a runtime success or retry.

`test_native_inference_waits_for_observation_after_consumption` withholds the
observer loop until the real startup owner reads the child's consumed receipt.
Removing the inference exit barrier causes the success/live-sample assertions
to fail. Both watchdog settings are covered. The matrix additionally checks
trial/formal admission and all enforcement modes.

Deadline and refusal semantics remain covered separately by injected-clock
startup tests (including late/missing consumption and late publication), the
real missing-ACK child test, and `test_gpu_runtime_protection.py`. Do not apply
the wiring clocks globally or to these refusal witnesses. No provider, GPU,
optimizer update, production default, or scientific identity changes are needed.

`test_native_wiring_survives_scheduling_stall_before_launch` delays supervision
by 1.1 seconds, beyond the synthetic observation's one-second age limit. Against
the original matrix this stops before spawn and surfaces a missing-ACK message;
the typed protection receipt identifies expired coverage and no child PID. With
the wiring clocks, the same delay preserves success without changing policy.

Shared startup construction lives in `tests/helpers/inference_startup.py`.
Clock injection and explicit preparation/acknowledgment budgets are independent;
existing native-launch callers retain their selected defaults. The offline
storage witness exercises the production post-publication ACK window across
the preparation deadline and rejects expiry even when a consumed receipt exists.
It does not monkeypatch a peer test module or assert only a fixture constant.
