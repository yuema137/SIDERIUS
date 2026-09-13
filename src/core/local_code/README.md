# Task-local Python packages

This module owns finite, content-pinned loading for the optional manifest
[`code_package` declaration](../../../docs/reference/task-composition.md).
It does not own plugin-family schemas, registries, scientific policy or process
supervision. The [modular example](../../../examples/synthetic_masked_regression/modular/README.md)
uses the public composition interface without changing framework source.

## Responsibilities

| module | responsibility |
|---|---|
| `capture.py` | validate relative Python-member declarations; capture immutable bytes and whole-set identity |
| `importing.py` | finite shared namespace/finder; captured-byte execution; rollback of newly imported modules and parent attributes |
| `binding.py` | run binding, member selection, inherited bootstrap and shared subprocess environment contribution |
| `transport.py` | immutable workspace sidecar; verify the captured member pins against child-visible files |
| `failure.py` | typed per-launch failure report and explicit-cause-only refusal recognition |
| `child.py` | optional pre-import entry guard and parent completion/unwind check; never spawns or supervises a process |

Omitting `code_package` retains existing single-file loading and identities.
For selected members, data-path, metric, model, loss, Health and other file
consumers share one namespace. Runtime namespace isolation includes location;
semantic identity excludes absolute paths and includes every listed member's
relative name and content hash. Identical relocated packages have equal semantic
identity but distinct Python classes in the same interpreter.

The parent executes captured bytes, not a later disk read. Children receive a
sidecar naming locators and the original hashes; the sidecar is not a source
overlay or a fresh hash authority. Every declared member is checked before child
package execution, including helpers not yet imported. Relative imports cannot
discover unlisted siblings. Installed third-party imports behave normally.

## Binding and transport

An unbound child may bootstrap inherited transport. An explicit root absence
masks stale inherited transport. A captured root binds its immutable snapshot;
an inherited child cannot replace that pin with a different or absent package.
Family registries retain their existing lifecycle; this is not a process-global
registry reset manager or support for concurrent composed runs.

The shared `core.subprocess_env.subprocess_env()` carries internal values:

- `SIDERIUS_TASK_CODE_MANIFEST`: workspace `task_code/<digest>.json` sidecar.
- `SIDERIUS_TASK_CODE_SHA256`: hash of that immutable sidecar.
- `SIDERIUS_TASK_CODE_FAILURE_CHANNEL`: private typed per-launch descriptor
  on guarded launches; nested children retain the same launch identity.

These are transport, not task settings. Do not hand-edit sidecars or failure
descriptors. A successful launch needs no failure report. A named refusal writes
`task_code/failures/<launch_id>.json`; the parent validates its package, transport
and launch identity before classifying it. An unreadable or mismatched declared
channel refuses rather than silently becoming an ordinary candidate error.

## Task-owned spawn pools

Inside a guarded framework child, a task may use the normal-importable public
initializer before Python unpickles helper-defined callables:

```python
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from core.local_code import bootstrap_code_package

with ProcessPoolExecutor(
    mp_context=get_context("spawn"),
    initializer=bootstrap_code_package,
) as pool:
    results = list(pool.map(task_helper, inputs))
```

The initializer installs the verified finder without eagerly executing an
arbitrary entry. Its optional `(manifest_path, digest)` arguments support an
explicit serialized carrier; if a framework failure descriptor is inherited,
the explicit transport must match it. An independent pool initialized with an
explicit carrier but no framework launch descriptor remains caller-owned
execution: it does not acquire a framework workflow/chain halt guarantee.

## Refusal and limits

`LocalCodeError` is a `RuntimeError`, deliberately not field-validation
`ValueError`: Pydantic must not convert package integrity into a config rejection.
Framework-owned catches preserve it, including explicit exception causes. The
root workflow records `code_package_integrity`, writes its chain halt marker and
exits 3 before retry, next iteration or result promotion. Ordinary model errors,
provider retries, Health verdicts and resource budgets keep their existing rules.

This is reproducibility machinery, not a Python security sandbox. Arbitrary task
or third-party code can catch exceptions; broken report storage or external
process termination can prevent diagnostics from surviving. A generic pool
failure is not automatically package-integrity evidence. The validator reviews
the captured entry only, not helper source recursively. See
[operating refusals](../../../docs/guides/operating-a-run.md#failures-and-refusals)
and [resume guidance](../../../docs/guides/workspaces-and-resume.md).

Focused evidence lives in `tests/unit/core/test_local_code_*.py`, the local-code workflow
and validator tests, and `tests/unit/examples/test_modular_masked_regression.py`.
