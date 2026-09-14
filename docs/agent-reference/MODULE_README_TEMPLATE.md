# Module README template

**Purpose of this template**: every major subsystem directory carries a
`README.md` that lets a person landing *in that directory* understand its
purpose and safe next step without first reading the design archive. A module
README is a **map of the directory and its boundaries** — the cross-cutting
*semantics* stay in the [mechanism references](mechanisms/README.md), which the
module README links instead of restating. One home per concept.

Instantiated for: [`workflows/`](../../src/workflows/README.md) ·
[`core/`](../../src/core/README.md) ·
[`execute_tools/`](../../src/execute_tools/README.md) ·
[`execute_tools/health_checks/`](../../src/execute_tools/health_checks/README.md) ·
[`ml_models/`](../../src/ml_models/README.md) ·
[`agent/schemas/`](../../src/agent/schemas/README.md). Node directories are the exception:
their `<node>.md` contract docs predate this template and are governed by
[`nodes/NODE_TEMPLATE.md`](../../src/nodes/NODE_TEMPLATE.md).

Rules:

- **The source is the authority.** Name modules and symbols; avoid line
  numbers in the README body (they rot). Where the README and the module
  disagree, fix the README.
- **State maturity honestly.** Anything not landed is marked with the status
  vocabulary (🟡 partial, 🧭 planned, ⚠ legacy) and names its owner.
- **Keep it a map, not a manual.** Deep semantics belong to a mechanism doc or
  the module's own docstrings; the README answers "what is here, what may I
  touch, what will refuse".
- **Update trigger**: a PR that changes a module's public surface, extension
  points or failure modes updates its README in the same PR (the existing
  node/skill doc-sync rule, applied to subsystems).

---

## Sections (all thirteen, in this order)

```markdown
# <module path> — <one-line role>

**Audience** / **Authority** header: who this is for; the statement that the
source wins.

## Purpose
What this directory is for, in ≤ 5 sentences, including what it is *not*.

## Public interface
The entry points someone outside the directory may call: classes, functions,
CLIs — named with their module. Group by file for multi-file packages.

## Inputs
What flows in: arguments, files read, environment variables, bindings.

## Outputs
What flows out: return types, files written, records, exit behaviour.

## Owned semantics
The rules THIS module is the single authority for. If a rule has a guard
test, say so.

## Non-owned semantics
The adjacent rules this module deliberately does NOT own, each with a link to
its owner (mechanism doc or module).

## Extension points
How new behaviour is added without editing this module — registries, plugin
surfaces, config seams. State explicitly where the extension path is NOT
(e.g. an import list that is bootstrap, not extension).

## State and filesystem effects
Everything it writes or mutates: workspace artifacts, global registries,
caches, environment. Include hidden/global state honestly.

## Failure modes
The named errors and refusals a caller will actually meet, and what each
means. Deliberate refusals are documented as the guard working.

## Files normally edited
What a contributor changes here for the common tasks — and under what rule
(citation requirements, guards to keep green).

## Files normally NOT edited
The frozen or high-risk surfaces, each with the reason (frozen contract,
single-authority rule, paper-spec pin).

## Minimal example
The smallest real usage — a snippet that runs, or the one command.

## Related tests
Where this module's tests live; the guard tests that pin its invariants.
```
