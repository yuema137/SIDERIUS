# `data/` — Oxford-IIIT Pet (identity manifests only; no data here)

This directory holds the **identity manifests** and their SHA-256 pins —
never the images (roadmap §22.23.10). Cloning SIDERIUS downloads no dataset.

## Acquisition (explicit user action; nothing is fetched by the framework)

Official source (use it as provenance, not a mirror):

```bash
# ~792 MB images + ~19 MB annotations — into a MACHINE-LOCAL directory outside the tree
curl -L -o images.tar.gz      https://www.robots.ox.ac.uk/~vgg/data/pets/data/images.tar.gz
curl -L -o annotations.tar.gz https://www.robots.ox.ac.uk/~vgg/data/pets/data/annotations.tar.gz
sha256sum annotations.tar.gz  # 52425fb6de5c424942b7626b428656fcbd798db970a937df61750c0f1d358e91 (2026-08-15)
```

**Decided by D14-2** (the deferral this paragraph carried): the
machine-local root reaches the framework as the data-path seam's OWN
`data_dir` (`EpochSamplingParams` / `EvalMaterializationParams` — the same
channel TIDMAD's `data_dir` uses; no new YAML). Acquisition is
`tools/example_packs/fetch_oxford_iiit_pet.py --dest <machine-local dir>
--extract` — verify-before-anything against the SHA-256 pins in
`PROVENANCE.md`; an in-tree `--dest` is refused.

## Manifests

| file | rows | meaning |
|---|---|---|
| `manifests/train.csv` | 2 946 | canonical TRAINING scope |
| `manifests/validation.csv` | 734 | canonical VALIDATION scope |
| `manifests/final.csv` | 3 669 | canonical FINAL-EVAL scope (= the official test list) |
| `manifests/SHA256SUMS` | — | integrity / provenance pins |

Columns: `image_id, class_index (0-based), official_class_id (1-37), scope`.
`image_id` is the official stem (`<Breed>_<n>`); the JPEG is
`images/<image_id>.jpg` in the official archive. The scopes are pairwise
disjoint; runtime resampling is forbidden (§22.9a). Derivation rule and
source hashes: `../PROVENANCE.md`.

Preparation (decode → resize → crop → tensor) is CODE since D14-2 —
`execute_tools/pets_data_path.py::decode_and_transform`, pinned by
`manifests/execution.json` (37 class-covering probe hashes). The gate
subsets `manifests/gate2_*.csv` are committed, derived first-N-per-class
from the frozen identity manifests, and — since Step 12 / PR-12d D5
(F-12d-5) — carry their own `SHA256SUMS` pins, because a Gate reads them.
Both pack writers re-pin the WHOLE manifest directory, so regenerating the
identity manifests can no longer silently drop the subsets' coverage.
