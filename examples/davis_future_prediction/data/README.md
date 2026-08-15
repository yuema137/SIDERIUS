# `data/` — DAVIS 2017 TrainVal 480p (sequence manifest only; no data here)

This directory holds the **sequence-level identity manifest** and its SHA-256
pin — never frames, never the archive (roadmap §22.23.10). Cloning SIDERIUS
downloads no dataset.

## Acquisition (explicit user action; nothing is fetched by the framework)

Official source (`https://davischallenge.org/davis2017/code.html`):

```bash
# ~833 MB — into a MACHINE-LOCAL directory outside the tree
curl -L -o DAVIS-2017-trainval-480p.zip https://data.vision.ee.ethz.ch/csergi/share/davis/DAVIS-2017-trainval-480p.zip
```

The archive holds `DAVIS/JPEGImages/480p/<sequence_name>/<frame>.jpg` (the RGB
frames this task consumes), `Annotations/` (segmentation masks — NOT used by
this task) and `ImageSets/2017/{train,val}.txt`. Where the machine-local
directory lives, how the framework is told about it, and the exact terms of
the downloaded artifact are decided / pinned by **D14** (roadmap §22.23.0,
§22.9a). At PR0 no framework component reads DAVIS data.

## Manifest

| file | rows | meaning |
|---|---|---|
| `manifests/sequences.csv` | 90 | `sequence_name, scope` — 60 `train` / 15 `validation` / 15 `final` |
| `manifests/SHA256SUMS` | — | integrity / provenance pin |

Sequence-disjoint by construction; runtime resampling is forbidden (§22.9a).
Derivation rule and source hash: `../PROVENANCE.md`.

**There is no clip manifest here.** Which `(sequence_name, start_frame)`
windows materialize (8 context → 4 future frames, stride 1; indicative caps
≤ 8 windows per train sequence, ≤ 4 per validation / final sequence), the
decode / resize rule and the tensor hashes are the EXECUTION-level manifest —
D14 in full. Prepared data will live in the workspace / machine-local data
area, never in the tracked tree.
