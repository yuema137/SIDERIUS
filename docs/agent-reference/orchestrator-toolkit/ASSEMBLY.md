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
- Run identity, protected infra/task roots, authorized data and artifact paths.
- Resolved authorized partition scope in the existing native `DataScope`
  representation, with its frozen task/run source and mapping to profile indices.
  A band or shard label alone is not this binding. The profile describes the
  dataset universe, which can be larger than this run's authorized subset.
  Declare complete-dataset scope explicitly when it is actually authorized.
- Exact framework revision and this checkout's frozen Python environment.
- Capability enablement and existing executor route, including task-composition
  bindings where required; a module import is not an executor service.
- Per-role provider/model/effort, identifying fixed settings and open choices.
- Resource and deadline authority, including how all calls share the budget.
- Authorized evidence, advice and retrieval sources; no inferred extra access.
- Required final artifacts and evaluator/submission route from the common task.

For required prerequisites, identify the concrete prepared artifact/data root or
the existing authorized preparation command/document. A vague statement that
"data may be materialized" makes the agent rediscover environment setup from
source. Keep these deployment facts in the run declaration, separate from
research scheduling choices. Give the exact Python path for helper commands as
well as node invocations.

This is a document, not a newly parsed configuration schema. Use actual paths
and supplied existing capabilities. Missing prerequisites remain limitations;
this overlay does not install a data service or expose private evaluator files.

## Protect infra and frozen inputs

Keep the installed infra checkout/package (including its configuration and
virtualenv) and the full frozen task tree read-only to the research process.
Do not chmod a shared development checkout. Use the existing deployment's
process/container read-only mounts or equivalent filesystem controls, with
outputs and generated-library state outside those roots. Protect the checkout's
Git metadata too when it lives outside a linked worktree. Verify protection from
inside the actual launch environment; a before/after hash check detects a change
but does not prevent one. Retain inventories as separate evidence.

The wrapper adds no single writable-root requirement for other scratch, logs
or caches. Existing frozen task requirements still apply. Protecting the two
inputs is a launch-environment responsibility, not a new SIDERIUS runtime feature.

## Deployment identity

Record task-package identity, installed infra revision and wrapper revision
separately. Verify the installed schemas/protocols and own virtualenv against the
chosen infra revision. A successful test of an isolated repair is not evidence
that another dependency pin includes it. Recheck the exact deployed combination
after the repair is integrated. Preserve the frozen task's original provenance;
record diagnostic overrides separately and resolve deployment mismatches before
a formal run, rather than silently rewriting the task package or its pin.

## Discoverability

Start a fresh coding-agent session from the assembled workspace. The kickoff
explicitly names `$siderius-toolkit` and asks the agent to read the task/run
instructions, without supplying answers that should be discovered below the
skill index. References are relative to the file containing each link.

Codex AGENTS.md loading follows ancestor instruction files at session startup;
skills use progressive disclosure, so referencing a child page does not itself
load it. Also qualify a kickoff without an explicit skill mention and a nested
working directory; these exercise discovery paths that an explicit invocation
can conceal. See [observed qualification](QUALIFICATION.md) for the test method,
failures and limits. Verify actual file reads, requested inputs and resulting artifacts in
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
