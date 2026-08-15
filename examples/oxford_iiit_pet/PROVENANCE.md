# Provenance — `oxford_iiit_pet`

## Data source (official — use it, not Kaggle / HF mirrors, as provenance)

- **Paper**: O. M. Parkhi, A. Vedaldi, A. Zisserman, C. V. Jawahar, *Cats and
  Dogs*, IEEE CVPR 2012.
- **Dataset page**: <https://www.robots.ox.ac.uk/~vgg/data/pets/>
- **Archives** (direct download, no credential):
  - `images.tar.gz` (~792 MB) — <https://www.robots.ox.ac.uk/~vgg/data/pets/data/images.tar.gz>
    — **NOT fetched by this PR, never committed** (raw data stays outside the tree, roadmap §22.23.10)
  - `annotations.tar.gz` (~19 MB) — <https://www.robots.ox.ac.uk/~vgg/data/pets/data/annotations.tar.gz>
    (redirects to `https://thor.robots.ox.ac.uk/pets/annotations.tar.gz`) — the ONLY artifact
    consumed at PR0, from a temporary location; not committed
- **Licence** (roadmap §22.9a, frozen wording): the dataset page states
  "Creative Commons Attribution-ShareAlike 4.0 International License",
  copyright with the original image owners (re-verified 2026-08-15). The
  archive's own `annotations/README` additionally notes: "Dataset is made
  available for research purposes only. Use of these images must respect
  the corresponding terms of use of original websites from which they are
  taken." Consult the source for the authoritative current terms.

## Metadata artifact actually used (fetched 2026-08-15, twice, identical bytes)

| item | value |
|---|---|
| URL | `https://www.robots.ox.ac.uk/~vgg/data/pets/data/annotations.tar.gz` |
| fetch date (UTC) | 2026-08-15T21:57:55Z (second fetch immediately after; SHA-256 identical) |
| size | 19 173 078 bytes |
| SHA-256 (archive) | `52425fb6de5c424942b7626b428656fcbd798db970a937df61750c0f1d358e91` |
| `annotations/list.txt` | 7 355 lines (6 `#` header lines + 7 349 entries) · SHA-256 `6a54ab256e22f7a33c6f17a7669e58ea5f6f9c7a080ec2622c205aefd4b354da` |
| `annotations/trainval.txt` | 3 680 entries · SHA-256 `408f3f609481b939c94634169e6413414b733a3faeba440cbdcc5c02142eebdc` |
| `annotations/test.txt` | 3 669 entries · SHA-256 `a5454003774ffe01f4f322756d3ba5495bae21cb30bb217ab285dbfa2bef245c` |
| official format | `Image CLASS-ID SPECIES BREED-ID`; CLASS-ID 1…37; only the first two columns are identity for this task |
| consistency checks | trainval ∩ test = ∅; every id's class agrees with `list.txt`; 37 classes in each list; per-class trainval count 93–100 (roadmap said "~200 images/class, ~7,400 images": 7 349 images total, ~199/class) |

Nothing else from the archive (trimaps, xmls) is used.

## Identity manifests — FROZEN derivation rule (design §3.2, OD-PR0-2)

- `final` = the official `test.txt` list (3 669 images).
- `train` / `validation` = per class, sort the official `trainval.txt` image
  ids lexicographically; the entry at 0-based position `i` goes to
  `validation` iff `i % 5 == 4`, else `train`. **No RNG, no seed — the rule
  is the provenance.** Result: train 2 946 · validation 734 (= 3 680).
- Row: `image_id, class_index (0-based = official CLASS-ID − 1), official_class_id, scope`;
  rows sorted by `(class_index, image_id)` so regeneration is byte-deterministic.
- Implementation: `tools/example_packs/oxford_iiit_pet.py` (`split_trainval`,
  `derive_manifests`); the rule is re-tested on a synthetic list in
  `tests/unit/examples/test_oxford_iiit_pet_pack.py`, independent of the fetch.

## SHA-256 pins (`data/manifests/SHA256SUMS`)

```text
f72580dcec11a5234904bacc1f98b3119c72d7bc374b9691169723502477d070  final.csv
b58e8791460ab3d5b172e7a95d4841dd603db1ecbd38bf43dafcecec522546ea  train.csv
6dfda127d8e44173064b8146600701135ea57d3a46d076859d9f91a300d7b16e  validation.csv
```

The pin is an **integrity / provenance pin**: it detects corruption and names
the exact bytes reviewed. It is NOT by itself an immutability proof (a
manifest and its pin can change together). What makes the identity canonical
is the frozen rule + the official source's recorded SHA-256 above + review of
any regeneration commit.

## Regeneration (explicit operator act)

```bash
curl -sSL -o /tmp/pets/annotations.tar.gz https://www.robots.ox.ac.uk/~vgg/data/pets/data/annotations.tar.gz
sha256sum /tmp/pets/annotations.tar.gz      # must equal the archive SHA-256 above
tar -xzf /tmp/pets/annotations.tar.gz -C /tmp/pets annotations/trainval.txt annotations/test.txt
.venv/bin/python -m tools.example_packs.oxford_iiit_pet --annotations-dir /tmp/pets/annotations
```

A regeneration that changes any manifest byte must be committed with its
reason and the new source SHA-256 recorded here.
