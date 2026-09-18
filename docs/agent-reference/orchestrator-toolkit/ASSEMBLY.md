# Assemble an additive runtime documentation package

## Runtime layout

Place the payload in the actual fresh coding-agent working directory:

```text
workspace/
  AGENTS.md
  SIDERIUS-RUN.md             operator-supplied run declaration
  .agents/skills/siderius-toolkit/
    SKILL.md
    references/...
```

The source package's own directory is not the running agent's workspace.
Reject path collisions: do not overwrite an existing AGENTS.md, skill or task
file. If the baseline already has an instruction file, choose a runtime layout
that preserves it and validate which ancestor instructions actually load.
Copying a skill into an unrelated checkout does not establish discovery.

## Run declaration

Supply `SIDERIUS-RUN.md` as an additional document, separate from common task
instructions and scientific advice. It should identify:

- Exact task-instruction path and any immutable baseline inventory.
- Run identity, allowed writes, authorized data and artifact paths.
- Exact framework revision and this checkout's frozen Python environment.
- Capability enablement and existing executor route, including task-composition
  bindings where required; a module import is not an executor service.
- Per-role provider/model/effort, identifying fixed settings and open choices.
- Resource and deadline authority, including how all calls share the budget.
- Authorized evidence, advice and retrieval sources; no inferred extra access.
- Required final artifacts and evaluator/submission route from the common task.

This is a document, not a newly parsed configuration schema. Use actual paths
and supplied existing capabilities. Missing prerequisites remain limitations;
this overlay does not install a data service or expose private evaluator files.

## Discoverability

Start a fresh coding-agent session from the assembled workspace. The kickoff
explicitly names `$siderius-toolkit` and asks the agent to read the task/run
instructions, without supplying answers that should be discovered below the
skill index. References are relative to the file containing each link.

Codex AGENTS.md loading follows ancestor instruction files at session startup;
skills use progressive disclosure, so referencing a child page does not itself
load it. Verify actual file reads, requested inputs and resulting artifacts in
the cold-start transcript. See the official [AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
and [skills guide](https://learn.chatgpt.com/docs/build-skills). Product behavior
is version-sensitive; record the actual CLI version in the qualification.

## Byte-preserving additions

Before adding the overlay, inventory the selected common public package:
relative file paths, file sizes, SHA256 and symlink targets if present. After
assembly, check the same path set and exact bytes; separately list every added
file. Treat a removed, overwritten, moved or newly exposed private file as a
failed assembly. A checksum of one task.md does not certify an entire package.

For a regular-file-only input tree, this existing Python pattern snapshots it
without reading unrelated directories. Choose separate output paths outside the
input tree. Symlinks need an explicit deployment policy; do not silently follow
one into private evaluator material.

```python
import hashlib
from pathlib import Path


def inventory(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Explicit symlink policy required: {path}')
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify_additions(before, after):
    changed = [p for p, digest in before.items() if after.get(p) != digest]
    if changed:
        raise ValueError(f'Common input changed or disappeared: {changed}')
    return sorted(set(after) - set(before))
```

Byte equality does not prove policy equality: review the added prose for budget
resets, relaxed access, changed evaluation, hidden advice or imposed scheduling.
Keep the operator inventory and verification records outside the agent payload.
