# Process-separated lifecycle test contract

`test_loop_resume.process_segments` owns the offline operation/segment process
fixture shared by resume, end, judge, dead-successor, and console-cost tests.
Forked operation and segment children retain test callbacks (pause requests,
synthetic tuning/provider results, and fault injection). They still establish
sessions, reap children, check process-group cleanup, and verify native receipts.
These process boundaries must not be replaced with in-process lifecycle calls.

`validation_child.install_fresh_validation_units` explicitly initializes CPU
autograd in the pytest parent before any segment forks. This reproduces the
ordering precondition of a broad package run even when one lifecycle test is
selected alone. It does not perform optimizer steps or GPU work.

Validation graph units execute in a new interpreter through the existing core
subprocess supervisor. The test launcher derives this checkout from its own
file and selects its Python executable with `sys.executable`; it does not borrow
another environment or set `PYTHONPATH`. The child installs the existing offline
`test_native.Provider` only for validator LLM calls, then runs the production
`unit_child.run_invocation_file` entry. Model import, forward/backward probes,
generated pytest, typed transport, workspace/composition checks, budget transport,
and receipt verification remain real. Other graph units retain their inherited
test doubles. No arbitrary parent monkeypatch is implicitly serialized.

The child records generated-pytest invocations and their actual `PytestLimit`
in `<tmp_path>/pytest_limits.jsonl`, then calls the real generated-pytest runner.
`test_resumed_segment_bounds_validator_pytest_by_its_own_worker_budget` consumes
that record and retains its assertions for both initial and resumed segments;
it no longer relies on a fork-inherited closure returning a fabricated pass.

Production already starts graph units with an executable subprocess in
`tools.candidate_worker.unit_runner.spawn_unit`; operation spawning and sandbox
execution also use `Popen`. The observed inherited-autograd defect is in the
fork-only test substitute, not evidence of a production launch defect. Runtime
deadlines, scientific defaults, prompt bytes, and verification identities remain
unchanged. Python may still warn about other fork/thread risks in the test
fixture; this change isolates the demonstrated autograd failure, not all
possible fork-sensitive libraries.

Validation must include the complete candidate-worker test directory after a
CPU backward pass in the parent, plus an isolated lifecycle witness. Removing
the fresh validation dispatch while retaining the parent warm-up must make
native validation reject and the existing pause/resume assertions fail.
