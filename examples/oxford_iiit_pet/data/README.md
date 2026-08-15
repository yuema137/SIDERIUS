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

Where that machine-local directory lives, and how the framework is told
about it, is decided by **D14** (the executable data path — roadmap
§22.23.0: whether the existing `tidmad_data_config.yaml` mechanism is
generalized or extended is D14's source-audited decision). At PR0 no
framework component reads Pets data.

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

Preparation (decode → resize → crop → tensor) is not defined here — the
EXECUTION-level manifest belongs to D14; prepared data will live in the
workspace / machine-local data area, never in the tracked tree.
