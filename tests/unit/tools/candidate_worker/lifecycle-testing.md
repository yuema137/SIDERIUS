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

Validation graph units execute in a new interpreter through production
`unit_runner.spawn_unit`, including its `unit_env()` and success/failure stderr
relay. Only `unit_command` is scoped to an offline test entrypoint. The test launcher derives this checkout from its own
file and selects its Python executable with `sys.executable`; it does not borrow
another environment or set `PYTHONPATH`. The bootstrap inserts only the trusted
checkout path derived from this helper, never the candidate workspace, so it can
load the test-only provider under Python safe-path mode. The child installs the existing offline
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
CPU backward pass in the parent, plus an isolated lifecycle witness. The original
inherited-autograd symptom depends on the host's native thread state: reverting
the fresh dispatch may still pass on CPU-only CI hosts. Warm-up establishes the
ordering precondition, not a portable guarantee of that failure.

The G4 run-total-token witness independently checks the exec boundary. It creates
`<tmp_path>/reported_calls.log` to explicitly opt in to `provider_usage` reporting;
the fresh validator installs that same wrapper only when this file exists. Each
provider response appends the fixed offline usage row to its production-bound
run ledger and a JSON witness containing label, iteration, PID, safe-path flag
and hash seed. No arbitrary parent monkeypatch or secret environment value is
transported. Non-G4 tests do not enable usage reporting.

G4 requires validator calls from both iterations, PIDs distinct from the inherited
providers, safe-path startup and the production default hash seed. Its total-token
assertions include those validator rows. These checks discriminate on CPU-only
hosts even when inherited autograd happens to work. Mutations disabling reporting,
using the raw ambient environment or dispatching validation in the inherited
process must fail G4. These are test-fixture witnesses; production already owns
the process/environment semantics and is unchanged.
