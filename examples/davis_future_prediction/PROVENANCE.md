# Provenance — `davis_future_prediction`

## Data source (official)

- **Paper**: J. Pont-Tuset, F. Perazzi, S. Caelles, P. Arbeláez, A. Sorkine-Hornung,
  L. Van Gool, *The 2017 DAVIS Challenge on Video Object Segmentation*,
  arXiv:1704.00675 (2017) — <https://arxiv.org/abs/1704.00675>.
- **Challenge page / downloads**: <https://davischallenge.org/davis2017/code.html>
  → `DAVIS-2017-trainval-480p.zip` (~833 MB, hosted at `data.vision.ee.ethz.ch`),
  direct download, no credential (HEAD-checked 2026-08-15 at the roadmap
  selection audit). **NOT fetched by this PR; its body is never read; never
  committed** (roadmap §22.23.10).
- **Official tooling**: <https://github.com/davisvideochallenge/davis-2017>
  (the challenge's published toolkit) — its `data/db_info.yaml` is the
  official sequence-list METADATA consumed at PR0 (below).

## Licence / provenance wording (frozen — roadmap §22.9a, per artifact)

The official DAVIS repository (fperazzi/davis README) states "DAVIS is released
under the BSD License"; the challenge-created annotations carry separate
CC BY 4.0 terms (2017 challenge rules); the challenge download page itself
states no licence. This SIDERIUS task consumes RGB FRAMES, not segmentation
annotation masks — no single licence is claimed for every DAVIS artifact.
D14 MUST verify and pin the exact terms applicable to the downloaded
TrainVal-480p artifact before the example's executable provenance is
considered complete.

## Metadata artifact actually used (fetched 2026-08-15; NO archive body)

| item | value |
|---|---|
| source | `https://raw.githubusercontent.com/davisvideochallenge/davis-2017/97d08bf8b6201abf15509a67a985db3745a75ccd/data/db_info.yaml` (pinned commit `97d08bf8`, 2017-06-07; identical bytes at `master` on the fetch date) |
| fetch date (UTC) | 2026-08-15T22:04:49Z |
| size | 12 688 bytes |
| SHA-256 | `b14a9c264d04ffc6f99a92985fe024a388a7ee08e115f65e4005b72527420c4b` |
| content used | `sequences[].name` and `sequences[].set` for `set ∈ {train, val}` ONLY — 60 `train`, 30 `val` (the file also lists 30 `test-dev` sequences and per-sequence `num_frames`; neither is consumed — `num_frames` is clip-level information and belongs to D14) |
| consistency | train ∩ val = ∅; no duplicate names; counts equal the official DAVIS 2017 TrainVal split (60 / 30) |

## Sequence identity — FROZEN derivation rule (design §3.3, OD-PR0-2)

- `train` = the 60 official train sequences.
- `validation` / `final` = the 30 official val sequences sorted by name; the
  entry at 0-based position `i` goes to `validation` iff `i % 2 == 0`, else
  `final` — 15 / 15, sequence-disjoint by construction. No RNG, no seed.
- Row: `sequence_name, scope`; rows sorted by scope order
  (train, validation, final) then by name — byte-deterministic regeneration.
- Implementation: `tools/example_packs/davis_future_prediction.py`
  (`parse_db_info`, `split_official_val`, `derive_sequence_manifest`); the
  rule is re-tested on a synthetic list in
  `tests/unit/examples/test_davis_future_prediction_pack.py`.
- **Clip identity `(sequence_name, start_frame)` is NOT derived here** — D14
  in full (operator, 2026-08-15). PR0 has no archive-listing / HTTP-range
  machinery.

## SHA-256 pin (`data/manifests/SHA256SUMS`)

```text
56ddf30f02c8d8cba0a4a4839a32e0c8e0d9e00609c81d93be6b5edf5e9656b2  sequences.csv
```

An **integrity / provenance pin** — it detects corruption and names the exact
bytes reviewed; it is NOT by itself an immutability proof. Canonical identity =
the frozen rule + the official metadata's recorded SHA-256 above + review of any
regeneration commit.

## Regeneration (explicit operator act)

```bash
curl -sSL -o /tmp/davis/db_info.yaml \
  https://raw.githubusercontent.com/davisvideochallenge/davis-2017/97d08bf8b6201abf15509a67a985db3745a75ccd/data/db_info.yaml
sha256sum /tmp/davis/db_info.yaml   # must equal the SHA-256 above
.venv/bin/python -m tools.example_packs.davis_future_prediction --db-info /tmp/davis/db_info.yaml
# alternatively: --lists train.txt val.txt (official one-name-per-line files)
```
