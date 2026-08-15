# Example pack — `davis_future_prediction` (Track C: RGB 8→4 future-frame prediction)

The persistent SPATIOTEMPORAL / REGRESSION contrast track (roadmap
`docs/design/siderius_generic_framework_upgrade.md` §22.9 Track C, frozen
specification §22.9a, example-pack governance §22.23). Fixed by the task
immutability policy.

## Task (frozen §22.9a) — a SIDERIUS-defined task on DAVIS frames

| aspect | value |
|---|---|
| dataset | DAVIS 2017 (Pont-Tuset et al. 2017), TrainVal 480p — official distribution, see `PROVENANCE.md` |
| task | **real-RGB FUTURE-FRAME PREDICTION** (NOT DAVIS's official segmentation benchmark): 8 context frames → next 4 frames, stride 1; segmentation masks are NOT used |
| input topology | float32 `[C, T, H, W] = [3, 8, 128, 224]`, values in [0, 1] — deterministic decode → fixed resize/crop to 128×224 (rule frozen by D14), NO augmentation / flip / random crop |
| target | float32 `[C, T, H, W] = [3, 4, 128, 224]` — dense multi-channel continuous tensor |
| training scope | the **60** official train sequences |
| validation scope | **15** of the 30 official val sequences (by sequence identity) |
| final-eval scope | the **other 15** official val sequences |
| identity | SEQUENCE-disjoint (never frame-level random splits: temporal leakage). **Clip identity `(sequence_name, start_frame)` — which windows materialize — is D14's in full** (operator decision, PR0 design review 2026-08-15) |
| training objective (R1) | MAE / L1 over the predicted future tensor |
| validation objective (R3) | mean validation MAE per epoch |
| training history (R2) | mean training MAE per epoch |
| golden metric (R4) | **MSE** over ALL predicted pixels × channels × future frames of the final-eval clips · direction LOWER · terminal — aggregation FROZEN as the global mean over clips × C × T × H × W (never an unequal mean-of-means) |
| optional | validation PSNR (checkpointed, data_range = 1.0); PSNR (higher, data_range = 1.0) and MAE (lower) as terminal secondaries — the same MAE computation is training objective, validation observation and terminal secondary (three lifecycle roles of one computation) |

## What this pack contains at PR0 (sequence identity + L0/L1 declarations)

```text
data/manifests/sequences.csv        SEQUENCE-level identity manifest — sequence_name, scope
                                    (60 train / 15 validation / 15 final; frozen rule in PROVENANCE.md)
data/manifests/SHA256SUMS           integrity / provenance pin
data/README.md                      how to acquire the official data (nothing fetched here)
declared/model_io_contract.json     the pack's OWN ModelIOContract instance:
                                    [B, 3, 8, 128, 224] float32 -> [B, 3, 4, 128, 224] float32
declared/metric_mse.json            the pack's OWN MetricSpec instances (mse ↓ golden; psnr ↑; mae ↓)
declared/metric_psnr.json
declared/metric_mae.json
PROVENANCE.md · STATUS.md
```

**No clip manifest exists in this pack** — deliberately. Materializing
windows needs per-sequence frame counts and the executable data path
(decode / resize / window rules), which belong to D14. `STATUS.md` records
"clip identity → D14".

`declared/` holds instance DECLARATIONS this pack owns (roadmap §22.23.1),
built through the REAL framework schemas (`agent/schemas/model_io_contract.py`,
`execute_tools/evaluation_metric.py`) and validated by
`tests/unit/examples/test_davis_future_prediction_pack.py`. The runtime does
not read them yet: binding a pack to a run is Step 12's.

## What the framework can / cannot do with this task today

See `STATUS.md`. In one line: the two declarable contracts are declared;
`DatasetProfile`, `DeliverableSpec`, frame reader / window materialization,
clip identity, a reference plugin and Gate subsets are D14 seams; task
binding is Step 12; health applicability is Step 08. There is no launcher for
this task yet — this pack does not claim to run.
