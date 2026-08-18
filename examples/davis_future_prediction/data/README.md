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
this task) and `ImageSets/2017/{train,val}.txt`. **Decided by D14-3** (the deferrals this paragraph carried): the
machine-local root reaches the framework as the data-path seam's OWN
`data_dir` (no new config channel); acquisition is
`tools/example_packs/fetch_davis.py --dest <machine-local dir> --extract
--check-layout` (verify-before-anything against the archive SHA-256 pin;
an in-tree `--dest` is refused); and the artifact's terms are verified and
pinned in `../PROVENANCE.md` (§D14-3 VERIFICATION — verdict COMPATIBLE).

## Manifest

| file | rows | meaning |
|---|---|---|
| `manifests/sequences.csv` | 90 | `sequence_name, scope` — 60 `train` / 15 `validation` / 15 `final` |
| `manifests/SHA256SUMS` | — | integrity / provenance pin |

Sequence-disjoint by construction; runtime resampling is forbidden (§22.9a).
Derivation rule and source hash: `../PROVENANCE.md`.

**Clip identity landed at D14-3.** `manifests/clips.csv` (600 rows:
`sequence_name, start_frame, scope`) records which windows materialize —
8 context → 4 future frames, caps 8 / 4 / 4 per train / validation / final
sequence — derived by the pure rule
`execute_tools/davis_data_path.py::clip_starts` from each sequence's
on-disk frame count (no RNG). `manifests/execution.json` carries the
decode / resize rule and 10 window probe hashes;
`manifests/gate2_*.csv` are the bounded Gate subsets (first clip of every
sequence). Frames themselves stay machine-local — never in the tracked
tree.
