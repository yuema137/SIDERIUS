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

### What a model plugin's config must declare

The three `PLUGIN_*` attributes are not the whole contract. A plugin's
**config class** is a plain `BaseModel`, so unlike every built-in it inherits
nothing — and two obligations that built-ins get for free must be declared by
hand:

| declaration | why | if you omit it |
|---|---|---|
| `model_type` on the config | the framework injects `model_config["model_type"]` into **every** plan before execution (`nodes/ml_hyperparameter_tune_agent/planning.py`), because every built-in config inherits the field from `BaseConfig` | under the permissive `extra` default the injected key is **silently dropped**, and the run fails later in the trainer with `AttributeError` when it reads `model_cfg.model_type` |
| `PLUGIN_OUTPUT_TYPE` on the module | optional, and defaults to `"classifier"` | a regression task is refused at admission for declaring a class alphabet its task does not have |

Leave `extra` at Pydantic's permissive default, as `BaseConfig` and both
contrast exemplars do. `extra="forbid"` turns that same injected `model_type`
— and any other field the framework adds that your config does not model —
into a hard plan rejection, and a rejected plan does **not** consume an
attempt, so an unsatisfiable schema burns the whole round budget without
training once.

> **These are two separate defects, not one.** It is tempting to read them as
> a single "the config disagrees with the plan" story; they are not, and the
> difference decides what you look for.
>
> - `extra="forbid"` **alone** produces the loud failure: six consecutive
>   rejected plans and a run that aborts having never trained.
> - A missing `model_type` **alone** produces the quiet one: plans validate,
>   nothing is rejected, and the failure surfaces a layer later inside the
>   trainer.
>
> Both defaults are correct for a 2-class classifier and wrong for most
> tasks, so both are invisible until a pack copies an exemplar that omitted
> them. Every shipped exemplar now declares both, enforced across all of them
> by `tests/unit/examples/test_lane_e_f10_plugin_model_config_contract.py`.

A pack may also ship a `description.md` for its model beside the plugin, at
`{declared model-plugin root}/{model_type}/description.md`. The tuner reads it
into the planner prompt; without it the prompt is silently thinner. It is
searched last, so it never shadows a workspace registration of the same model
type.

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

**Across iterations in one workspace** — promoted model/loss plugins and the capability index
(`_capability_index.json`) live in the **generated-capability library**,
resolved by `core/generated_library.py`:

```
{workspace}/generated_library
```

Layout under the root: `models/`, `losses/`, `_capability_index.json`.
Workflow and standalone-node entry points derive this root from the configured
workspace before constructing any capability registry. Promotion writes here;
later iterations preload from here. They do not scan another workspace, the
user's home library, or the checkout-level `agent_generated/` fallback.
**No production path writes into or implicitly imports generated capabilities
from the repository checkout.**

`SIDERIUS_GENERATED_LIBRARY_DIR` remains the subprocess transport and a
low-level compatibility override for callers that do not use a supported
entry point. A relative override is refused because resolving it against the
current working directory could recreate checkout pollution. Unbound legacy
callers retain the historical per-user default and read-only checkout fallback
during the migration; supported workspace-bound execution does not.

Each run's invariants lock records its workspace-derived library root
(`generated_library: {root, source}`) — provenance, recorded and never
compared. Two workspaces under one user therefore have isolated candidate
pools by default, while iterations in one workspace retain validated
capabilities for resume and reuse.

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
- [`ml_models/README.md`](../../src/ml_models/README.md) — the model registry and plugin loader
