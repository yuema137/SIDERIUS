# Native workspace writers

Native Linux launches exclude a second cooperating writer to the same workspace.
Captured launches also retain a durable claim when cleanup cannot be established.
Create the workspace's parent directory before launch.

Inspect a selected workspace without changing its state:

```bash
.venv/bin/python -m core.native_writer inspect --workspace /external/runs/run
```

An `unresolved` claim requires verified recovery through the limited
[detached continuation route](../../tools/candidate_operations/README.md#continue-a-captured-native-chain).
This inspection interface cannot authorize it. Keep control files intact; restarting or deleting a lock file
does not prove that all writers stopped. See [the contract](native-writer-contract.md)
for support boundaries and lifecycle behavior.

`registered_idle` is not proof that every descendant stopped or permission to
resume. Ordinary successful children retain the existing cooperative process
semantics; deliberately escaped daemon writers are unsupported.
