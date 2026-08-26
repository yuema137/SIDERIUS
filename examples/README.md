# `examples/` — persistent example task packs

**Audience**: anyone looking for a worked, honest example of a SIDERIUS task
package.
**Authority**: each pack's own `STATUS.md` (maturity) and `PROVENANCE.md`
(dataset source and licence); the roadmap is the status authority those
files mirror. Template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../docs/agent-reference/MODULE_README_TEMPLATE.md).

## Purpose

Evidence of tested breadth, one directory per example task. These packs are
**data and declarations plus pack-local plugins** — production code never
imports from `examples/`; plugin files here reach a run only as *source*,
loaded dynamically through explicit references.

## Public interface

A thin index — the packs speak for themselves:

| pack | task | declared maturity (see its `STATUS.md`) |
|---|---|---|
| [`tidmad/`](tidmad/README.md) | 1-D SQUID signal denoising | production-backed read-only projection (Track A runs at L4 through the operator surface) |
| [`oxford_iiit_pet/`](oxford_iiit_pet/README.md) | 37-way RGB breed classification | **L4** — the composed production chain executed it end to end (G-12d) |
| [`davis_future_prediction/`](davis_future_prediction/README.md) | RGB 8→4 future-frame prediction | **L4** — the composed production chain executed it end to end (G-12d) |
| [`quickstart/`](quickstart/README.md) | small tabular onboarding task | L2 — executable components + composition-proven, with a live-witnessed bounded composed chain through real training; scoring leg not yet witnessed |

Read [supported tasks and current maturity](../docs/concepts/supported-tasks.md)
for what those levels mean before relying on any pack.

## Inputs

Datasets are never committed. Pets and DAVIS are fetched by their tools
under `tools/example_packs/`; the quickstart materializes its four sha-pinned
CSV shards from its own notebook/README instructions; TIDMAD's raw `.h5`
files are staged by the operator. Committed identity manifests (sha-pinned
file lists) make a fetched dataset verifiable.

## Outputs

Nothing at rest. A pack is consumed by pointing an entrypoint at its
composition manifest (shipped under
[`configs/task_composition/`](../configs/task_composition/) — the manifests
point *into* the packs; the packs themselves carry no top-level manifest).

## Owned semantics

Each pack owns its declarations (`declared/`), its plugins (`plugins/`), and
its honesty files. `STATUS.md` states what the pack can *actually* do —
"declared" and "executed" are kept apart deliberately.

## Non-owned semantics

- What a manifest section means → the
  [task composition reference](../docs/reference/task-composition.md).
- How the packs' plugins are loaded and identity-pinned →
  [plugins and generated code](../docs/concepts/plugins-and-generated-code.md).

## Extension points

A new example pack is a new directory following the same shape:
`declared/` + `plugins/` + `README.md` + `STATUS.md` + `PROVENANCE.md`,
bound by a manifest that lives *outside* `examples/`. An out-of-tree task
needs no pack here at all.

## State and filesystem effects

None. Datasets land wherever the fetch tools are pointed.

## Failure modes

The governance guards below refusing a change is the system working, not an
obstacle to route around.

## Files normally edited

A pack's own files, together with its `STATUS.md` when maturity actually
changes (promotion requires execution evidence, per the packs' own headers).

## Files normally NOT edited

**Governance, enforced by `tests/unit/examples/test_pack_governance.py`:**

- **No top-level task YAML under `examples/`** (PR0 rule): a
  `task_config.yaml`-shaped file is legitimate only when a shipped manifest
  *binds* it (the quickstart's `declared/task_config.yaml` is bound by
  `configs/task_composition/quickstart.yaml`; an identical YAML nobody binds
  is a refused parallel copy).
- Underscore-prefixed pack plugins (`_quickstart_task.py`,
  `_pets_metrics.py`, …) are skipped by every directory scanner **by
  convention** — their explicit `file:`/`kind: file` references are the only
  loading path. Do not rename them into scanner visibility.

## Minimal example

```bash
bash sdsc_submission_scripts/run_chain.sh … \
    --task_composition configs/task_composition/quickstart.yaml \
    --data_dir /path/to/materialized/quickstart/data
```

## Related tests

`tests/unit/examples/` — pack governance, per-pack declaration pins, health
families, reference plugins, the quickstart composition suite, and the
maturity-vocabulary guard.
