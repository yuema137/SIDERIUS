# Native workspace writers

Native Linux launches exclude a second cooperating writer to the same workspace.
Captured launches also retain a durable claim when cleanup cannot be established.
Create the workspace's parent directory before launch.

Inspect a selected workspace without changing its state:

```bash
.venv/bin/python -m core.native_writer inspect --workspace /external/runs/run
```

An `unresolved` claim requires verified recovery that is not yet available through
this interface. Keep the control files intact; restarting or deleting a lock file
does not prove that all writers stopped. See [the contract](native-writer-contract.md)
for support boundaries and lifecycle behavior.
