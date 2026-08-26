# Plugins and generated code

**Audience**: anyone supplying their own code to a run — or wondering where
the code the agents *wrote* actually lives.
**Answers**: the plugin families, how each is declared and loaded, what pins
their identity, and where generated artifacts go (spoiler: never into the
repository checkout).

Implementer depth — the full family table, namespace isolation, digesting
rules — is the [plugins mechanism reference](../agent-reference/mechanisms/plugins.md).

---

## The plugin families, by how they are declared

SIDERIUS is extended with code in two structurally different ways:

**Manifest-declared** (named in the task composition manifest, loaded by
`module:` or `file:` reference): the task **data path** (with its optional
scope/anchoring sibling capabilities), the **evaluation metric** (primary
and secondaries), and the task's **health checks and view providers**
(named in the task health config's `plugins:` list and registered through
the public `register` / `register_view_provider`). A `file:` reference is
how a task lives outside the SIDERIUS tree: its content sha256 joins the
run's semantic fingerprint, so editing the plugin between a run and its
resume is detected. `module:` references carry no digest.

**Directory-scanned** (found by scanning directories, never named in the
manifest): **model plugins** and **loss plugins** — the two families the
agents themselves generate.

```
SIDERIUS_PLUGIN_DIRS   →  model plugins:  PLUGIN_MODEL_TYPE / PLUGIN_CONFIG_CLASS / PLUGIN_MODEL_CLASS
SIDERIUS_LOSS_DIRS     →  loss plugins:   PLUGIN_LOSS_TYPE / PLUGIN_LOSS_CONFIG_CLASS / PLUGIN_LOSS_CLASS
```

A model plugin is a single Python file declaring those three attributes (its
config class, its `nn.Module`), satisfying the task's declared forward
contract — for TIDMAD, `[B, T] int → [B, 256, T] float`. Directory scanners
skip `_`-prefixed files, which is how example packs ship manifest-referenced
plugins next to a scanned directory without them being picked up implicitly.
A composed run's manifest can also name pack plugin directories
(`model_plugins:` / `loss_plugins:`), which are unioned into every child
process's scan path.

## Registration: the two-phase rule

Whatever the family, registration follows one lifecycle rule:

> **Same id + same content ⇒ idempotent. Same id + different content ⇒
> refused.**

A registry hit is never identity proof by itself — the parent pins a
per-family content identity **captured at registration**, and a child
verifies it before consuming. (Captured, not re-read: re-deriving the
identity at spawn time would read whatever is on disk *now*, so the pin
would follow the very edit it exists to catch.) A plugin that raises during
registration is rolled back and the run refused. Identity hashes cover
content only, never absolute paths — the same package at two locations has
one identity, which is what makes an out-of-tree package relocatable.

## Where generated code lives

Two different lifetimes, two different places:

**Per run** — every run stages the plugin code that actually executed into
`{workspace}/plugins/{run_name}/`. That directory *is* the science of the
run: the model code the agents wrote, exactly as it ran, restored
automatically on resume.

**Across runs** — promoted model/loss plugins and the capability index
(`_capability_index.json`) live in the **generated-capability library**,
resolved by `core/generated_library.py`:

```
SIDERIUS_GENERATED_LIBRARY_DIR    absolute path; "~" expanded; empty = unset;
                                  a non-empty RELATIVE path is refused loudly
    else
~/.siderius/generated_library     the per-user default
```

Layout under the root: `models/`, `losses/`, `_capability_index.json`.
Promotion writes here; startup preloads and the no-env-var scans read here
first. **No production path writes into the repository checkout** — the
checkout-level `agent_generated/` directory is a *read-only legacy
fallback*, kept so a pre-migration checkout keeps resolving what it
promoted. (The old behaviour, where every run mutated the checkout and two
collaborators sharing one silently contaminated each other's runs, is the
defect this design removed.)

The refusal of a relative override is deliberate: resolved against the
current working directory, a relative path launched from inside the checkout
would recreate exactly that checkout pollution. The error message says so
and names the fix.

Each run's invariants lock records which library root it resolved
(`generated_library: {root, source}`) — provenance, recorded and never
compared, so the same science on a host with a different library location
resumes legally. Two workspaces under one user share the library by
default; point `SIDERIUS_GENERATED_LIBRARY_DIR` at per-project roots for
isolated candidate pools.

## What refuses, and why

| you did | it says / does |
|---|---|
| declared both `module:` and `file:` (or neither) | composition refuses — exactly one |
| declared an `id:` that differs from the implementation's own | refused: the implementation is the authority on its own id |
| registered a second implementation under an id with different content | refused (the two-phase rule) |
| edited a `file:`-declared plugin between run and resume | resume fails at startup — the pinned digest moved |
| set `SIDERIUS_GENERATED_LIBRARY_DIR` to a relative path | `MalformedGeneratedLibraryOverride`, with the reason and the fix in the message |

## Where to go next

- [Plugins mechanism reference](../agent-reference/mechanisms/plugins.md) — the full family table and source map
- [Task composition reference](../reference/task-composition.md) — `module:` vs `file:` shapes
- [Bring your own metric](../guides/bring-your-own-metric.md) · [Bring your own health checks](../guides/bring-your-own-health-checks.md)
- [`ml_models/README.md`](../../ml_models/README.md) — the model registry and plugin loader
