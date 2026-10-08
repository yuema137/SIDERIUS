# Bring your own train/test split

This is the third guide in the bring-your-own family
([metric](bring-your-own-metric.md) · [health
checks](bring-your-own-health-checks.md)). It was deliberately written after
the manifest's omission semantics were finished (#268/#286): everything below
describes fail-closed behavior, not a fail-open corner.

## Where a split lives

Two declaration surfaces cooperate; you own both in your package.

1. **`dataset_profile`** (a required manifest section) declares the corpus
   geometry the framework may know: `partition_count` (how many input
   partitions exist), `anchor_selection_files`, `health_peek_files`. The
   framework carries it and pins it — it never invents members.
2. **`TaskScopeCapability`** (an optional sibling your `task_data_path`
   module may implement, beside the frozen four-method `TaskDataPath`)
   constructs the actual training/evaluation scopes: which of your samples
   train, which evaluate, how a snapshot is drawn. Your capability builds
   them; the framework transports them to every child process as a
   sha256-verified artifact — raw scope JSON never rides argv.

The quickstart pack is the worked example: its
`examples/quickstart/plugins/_quickstart_task.py` implements the capability
(snapshot/anchors/target construction with eval-shard isolation), and its
`declared/dataset_profile.json` declares the four-partition geometry the
scope capability serves.

Your package must also supply the
[required task-owned split evidence](define-a-task.md#required-task-owned-split-evidence).
That is the canonical onboarding obligation; the identity mechanisms below
preserve transport integrity and comparability, not scientific disjointness.
Two correctly hashed scopes can still contain the same held-out identity.

## What enters run identity — the comparability consequences

The papers' comparability rule (S13/S14) is enforced by two identity layers.
Your split participates in both; know which carries what.

- **The run-invariants lock** pins the RESOLVED data scope (`--data_scope`
  and its expansion), the health-gate enablement + effective-config sha, and
  the launch identity. Two runs whose resolved scopes differ are
  incomparable, and a resume across the difference **fails at startup**
  through the existing `RunInvariantsViolation` machinery.
- **The composed semantic fingerprint** pins your declarations and your
  code: the `dataset_profile` contents, your `task_data_path` instance
  config, your plugin content digests, and — since #255 — the
  **registration-captured content identity of your data-path implementation
  itself**. Editing the implementation that draws your split (a crop size, a
  window rule, a selection constant) moves the fingerprint; two runs with
  different split code are never silently "the same run".

Consequence worth stating plainly: aggregate scalars are only comparable
within one scope and one split implementation. If you change either,
expect the old workspace to refuse its resume — that refusal is the
comparability discipline working, and there is no bypass flag.

## Fail-closed boundaries

- A **partial scope** admits only `snapshot` sampling: an operator config
  requesting anything else errors at startup, and an LLM-planned strategy is
  normalized with recorded provenance (`docs/design/enable_partial_file_list.md`).
- The legacy partition SampleSet route validates supplied membership with
  `validate_sample_set` at sandbox execution boundaries. Opaque task-owned
  scopes instead use the task's construction/materialization contract and
  digest-verified transport; they are not parsed as SampleSets.
- `health_gate_files` must be a subset of the resolved scope, validated at
  startup.
- A scope artifact whose sha256 does not match its transport digest is
  refused **before deserialization** in every child.
- A composed manifest that omits `deliverable:` while its implementation
  does not name its own artifacts is refused at compose time (#268) — the
  same omission-vs-named-absence rule your other sections follow.

## The minimum your package supplies

```text
declared/dataset_profile.json     # partition_count + the two peek lists
plugins/_your_task.py             # TaskDataPath + (optionally) TaskScopeCapability
composition.yaml                  # dataset_profile: {config: declared/dataset_profile.json}
```

The four-method `TaskDataPath` can consume already-supplied scopes without
`TaskScopeCapability`. The composed workflow's scope-construction path requires
the sibling's four methods, regardless of whether your data is uniform,
windowed or grouped. Missing methods cause `TaskScopeCapabilityError` before
child processes launch; the framework does not invent a default split from
your declared partitions. Implementing the capability does not itself prove
that the scopes are scientifically independent.
