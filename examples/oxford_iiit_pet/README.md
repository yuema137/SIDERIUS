# Example pack — `oxford_iiit_pet` (Track B: 37-way RGB pet-breed classification)

The persistent IMAGE / CLASSIFICATION contrast track (roadmap
`docs/design/siderius_generic_framework_upgrade.md` §22.9 Track B, frozen
specification §22.9a, example-pack governance §22.23). Fixed by the task
immutability policy: not replaced because a Step is difficult, semantics not
modified to make an abstraction pass.

## Task (frozen §22.9a)

| aspect | value |
|---|---|
| dataset | Oxford-IIIT Pet (Parkhi, Vedaldi, Zisserman, Jawahar 2012) — official VGG distribution, see `PROVENANCE.md` |
| task | 37-way pet-BREED classification from real RGB JPEG images (~200 images/class); ROI / trimap annotations are NOT inputs |
| input topology | raw RGB JPEG, VARIABLE H/W → deterministic preprocessing: decode RGB (3 channels) → aspect-preserving resize, shorter side 160 px → center crop 144×144 → float32 `[3, 144, 144]` = pixel/255.0; NO augmentation (interpolation rule frozen by D14) |
| target | integer class id 0…36 (scalar categorical); `class_index = official CLASS-ID − 1`; the breed name is the image-id prefix (e.g. `Abyssinian_100` → class 0) |
| training scope | breed-stratified deterministic 80 % of the official trainval list — **2 946 images** |
| validation scope | the disjoint 20 % of the official trainval list — **734 images** |
| final-eval scope | the official test list only — **3 669 images** |
| training objective (R1) | categorical cross entropy |
| validation objective (R3) | mean validation cross entropy per epoch |
| training history (R2) | mean training cross entropy per epoch |
| golden metric (R4) | 37-class **accuracy** on the final-eval scope · direction HIGHER · terminal |
| optional | validation accuracy (checkpointed); **macro-F1** (higher, terminal); `log_loss` (lower, terminal — **blocked by D16**, see `STATUS.md`) |

## What this pack contains at PR0 (identity + L0/L1 declarations)

```text
data/manifests/{train,validation,final}.csv   IDENTITY manifests — image_id, class_index,
                                              official_class_id, scope (derived from the official
                                              annotation lists by the frozen rule in PROVENANCE.md)
data/manifests/SHA256SUMS                     integrity / provenance pins of the three manifests
data/README.md                                how to acquire the official data (nothing fetched here)
declared/model_io_contract.json               the pack's OWN ModelIOContract instance:
                                              [B, 3, 144, 144] float32 -> [B, 37] float32
declared/metric_accuracy.json                 the pack's OWN MetricSpec instances (accuracy, macro_f1)
declared/metric_macro_f1.json
PROVENANCE.md · STATUS.md
```

**The manifests are the authority for which images belong to which scope**
(§22.9a: "the manifest is the authority, the seed is provenance only; the
three scopes are disjoint; runtime resampling is forbidden"). They were
derived by the frozen rule, from official metadata only, and pinned; a
regeneration is an explicit operator act with provenance
(`.venv/bin/python -m tools.example_packs.oxford_iiit_pet --annotations-dir <tmp>/annotations`).

`declared/` holds instance DECLARATIONS this pack owns (roadmap §22.23.1) —
built through the REAL framework schemas (`agent/schemas/model_io_contract.py`,
`execute_tools/evaluation_metric.py`) and validated by
`tests/unit/examples/test_oxford_iiit_pet_pack.py`. They are not snapshots
of a production authority (contrast `examples/tidmad/resolved/`), and the
runtime does not read them yet: binding a pack to a run is Step 12's.

## What the framework can / cannot do with this task today

See `STATUS.md`. In one line: the two declarable contracts are declared;
`DatasetProfile`, `DeliverableSpec`, reader/preprocessing, a reference
plugin and Gate subsets are D14 seams; task binding is Step 12; health
applicability is Step 08. There is no launcher for this task yet — this pack
does not claim to run.
