# Native chain capture contract

`tools.native_chain` captures `native-standard-chain/v1`: fresh foreground lilab,
start 1, no seeds, no fixed candidate plan. The shell remains the only scheduler
and argument/default owner. `models.py` owns typed external inputs; `review.py`
uses shell FD export, then existing sandbox `check_task` and
`inspect_environment(bind_launch=True)`. No semantic review receipt is produced.

Review requires checkout cwd, canonical dedicated paths, absent native workspace
and output, existing parents, and separate output/source/data/run locations.
The request envelope has a 1 MiB ceiling; `input_max_bytes` bounds declaration,
individual pinned files, generated argv and final capture reads. Export uses an
inherited descriptor containing UTF-8 NUL-separated tokens; human stdout has no
control meaning. Existing scientific repeats retain native last-value behavior.
Protected controls and aliases cannot appear in `chain_args`.

The capture preserves successful task/settings observations, installation and
finite owner-selected file pins, exact source bytes and exact argv. It publishes
write-once after verifying copied input bytes and rechecking bindings. Failed
review may leave private task/environment diagnostics but never a successful
partial capture or native run artifacts. Sandbox failure has no unsandboxed fallback.
Package identity and file closure retain existing owner limitations; datasets are
observed external resources. Concurrent same-user mutation is not made atomic.

## Enforcement

`check.admit` runs after exact-source probing and before resume inspection or
workspace creation. It binds the exact shell vector after removing only paired
capture controls and optional `--dry-run`; it refuses every existing workspace,
including dangling symlinks. Each dispatch regenerates standard argv through
that same shell export owner for its scheduled index and rechecks original files
and installation. Capture-only refusal 78 returns directly from the shell loop,
including when a child returns it; it writes no scientific stop record.

`iteration` invokes the existing native main once with `NativeChainLaunchContext`.
`LaunchExpectations` owns shared entry/composition/runtime/invariant comparisons;
setup review retains its serialized fields and receipt behavior. Native final
comparison copies the observed complete projection and substitutes exactly
`start_iteration` and actual `RestoredState.resolved_source_paths`; added/missing
or changed other fields refuse. No executable config is reconstructed from JSON.
Native-specific refusals escape package/scientific failure handlers before
`run_workflow`; unrelated exceptions keep native behavior. Composition imports,
iteration directory, token and restoration artifacts can precede this final check.
No arbitrary graph, detached operation, GUI, Slurm capture, effectful resume or
writer lease is introduced.

## Read-only checkpoint consumers

`inspection.py` owns the former inspector's legacy IterationReport chain reader,
including display details and valid no_records→PARTIAL projection. Existing
inspector CLI defaults and next-iteration behavior remain unchanged.
`observation.py` adds an explicit strict bounded projection for detached operations:
canonical scheduled workspace/indices, no-follow files, no artifact escape,
iteration-count/directory/aggregate-byte limits and native token sidecar only.
It verifies and parses the same output bytes through the existing manifest and
HyperparamTuningOutput owners. It never controls native scheduling or resume.
Legacy manifests expose separate false verification flags, never invented trust.
The observer's two concrete policies preserve historical terminal comparison;
version defaults and operation read/write behavior belong to the
[candidate operation contract](../candidate_operations/candidate-operations-contract.md#captured-native-chain-operation).
