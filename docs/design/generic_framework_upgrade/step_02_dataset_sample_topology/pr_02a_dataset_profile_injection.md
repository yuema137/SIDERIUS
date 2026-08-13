# PR 02a — Dataset Profile injection (Step 02, child 1 of 3)

## Status

**DESIGN DRAFT — pending the parent's operator freeze. NOT FROZEN.
IMPLEMENTATION NOT AUTHORIZED.**

Parent (governance, ownership, DAG, aggregate acceptance):
[`../step_02_dataset_sample_topology.md`](../step_02_dataset_sample_topology.md).
This child owns only its own scope, evidence and checkpoints. It exists
because the parent's §6 decomposition audit found three independently
mergeable units; if the operator answers Q1 with ONE PR, this document
folds back into the parent.

Position in the DAG: **first**. `02b` and `02c` both depend on it.

## 1. Scope

**OWNS** — the dataset declaration and the production DATA PATH that
reads it:

- file topology: families, index space, counts, name patterns;
- sample decomposition geometry (`psd_segment_length`,
  `segments_per_file`) and the sample-shape **legality rule**;
- the dtype + offset **encoding declaration**;
- **channel identity** — which in-file channel is the model INPUT and
  which is the TRUTH (parent §1.6);
- derived-artifact **INDEXING** by input identity.

**DOES NOT OWN**: selection/SampleSet semantics (02b), group semantics
(02c), deliverable naming/layout/attrs (Deliverable Contract),
`segmentation_size` itself, model I/O semantics (Step 03).

**Boundary that needs care (parent §13b A1).** `scoring_utils.py`
handles BOTH the raw validation filename (Step-02-owned input topology,
inlined at `:389`, `:444`) and denoised deliverable files. This PR
routes ONLY the raw-validation half through the profile. **Any diff
touching a denoised/deliverable filename template is a scope leak and a
STOP.**

## 2. Why this is a PR

After it merges, the production data path — training engine, inference
and scoring — resolves filenames, geometry, legality, encoding and
channel identity from a **resolved profile argument** instead of
module-level constants. Pointing those consumers at a differently-shaped
dataset becomes a declaration change.

Its risk class is its own: a changed filename or `data_shape_class`
string invalidates measurement-store keys. That deserves its own review
and rollback boundary.

## 3. Implementation plan (behaviour, not code shape)

Commit boundaries are indicative; the implementer chooses the exact
decomposition (parent §13a).

1. **Capture the missing baselines FIRST** (parent §5) — the
   validation-name-vs-inlined-literal pin, the encoding-declaration
   tensor pin, and the channel-resolution tensor pin. Capture-first is
   an acceptance criterion, not a nicety (the S1-E precedent): a
   baseline captured after the change pins the changed behaviour and
   proves nothing.
2. Declare the profile (shape is implementation-time) and resolve it.
3. Migrate consumers to injection, module by module, killing the bare
   constant imports and collapsing the `scoring_utils` re-export hop
   (parent §1.2).
4. De-duplicate the legality restatements: the tuner's inline
   `psd % segmentation_size` check and the time-skill's hardcoded
   "10,000,000" prose (parent §1.3). Semantic commit, not a PR.
5. Correct the stale comment surface if any is found alongside.
6. Contrast rungs 4.8-A and 4.8-D as **two separate single-axis
   fixtures**.

**Open child-level decision (parent §13b A5).** `DatasetConfig` today
carries TIDMAD filename patterns as CLASS defaults. This PR must decide
explicitly whether they remain as a documented regime-A compatibility
adapter or become required declarations — and must NOT inherit them
silently as "generic defaults".

## 4. Compatibility contract (strongest criterion per surface)

| Surface | Criterion | Baseline |
|---|---|---|
| Resolved profile | deep-equals today's `TIDMAD` field by field | EXISTS (Step 00) |
| Legality list | exact 36-entry `valid_segmentation_sizes()` | EXISTS |
| Training filename | `training_file_name(0)`/`(19)` byte-identical | EXISTS |
| Validation filename | profile-produced name == the string the scorer/inference inline today | **MISSING → capture first** |
| `data_shape_class` | exact `psd10000000_seg200_files20` | EXISTS |
| Encoding | declaration produces byte-identical loaded tensors | **MISSING → capture first** |
| Channel identity | resolved channels produce byte-identical input/target tensors | **MISSING → capture first** |
| Rendered prompts | proposer known-constraints + planner divisor list byte-identical | EXISTS |

## 5. Checkpoints

| CP | Closing evidence |
|---|---|
| 0 | the three missing baselines captured BEFORE any extraction |
| A | every §4 criterion byte-identical under TIDMAD |
| B | 4.8-A and 4.8-D pass, each varying exactly one axis |
| C | training engine, inference AND the scoring path consume the resolved profile in production; **at least one production load path reads the ENCODING declaration** (parent §13b A4 — not closable otherwise) |
| D | affected package tests + mutation dossier + ONE terminal full suite at the final executable head + exact-head CI |

**Mutations** (each must red, then be restored): delete the injection
hop so a consumer falls back to the module constant; swap the resolved
input/target channel; perturb one geometry field and confirm
`data_shape_class` is protected by its pin.

## 6. Gates

Per the parent §10 and roadmap §17.0, instantiated from
`docs/gates/gate_testing_standard.md`:

- **Gate 1 — NOT REQUIRED.** This child's commit types are "Config
  files, YAML, schema-only" and "New loader/renderer (pure Python)" →
  the table says **Unit only**. It changes no LLM-facing prompt, and the
  prompt bytes it could touch are golden-pinned.
  **Flip condition**: if implementation changes any rendered prompt
  byte, this child takes Gate 1.
- **Gate 2 — not run by this child.** It runs ONCE at the Step level on
  the assembled head (parent §10.2).
- **Checkpoint C** is this child's production-boundary evidence.

## 7. Stop conditions

- a denoised/deliverable filename template appears in the diff;
- `data_shape_class` string changes;
- a golden outside the declared set changes;
- a profile field lands without a production consumer;
- rendered prompt bytes change without taking Gate 1.
