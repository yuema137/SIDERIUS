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
