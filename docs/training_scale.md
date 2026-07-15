# SIDERIUS Training Scale Reference

## Paper Baseline (TIDMAD train_nosplit.py)

- Files: 20 training files
- Samples per file: 2,000,000,000
- Segmentation size: 40,000 samples/segment
- Subsampling: `sample_size=5` (20% of segments per file)
- Segments per file per epoch: 10,000
- Optimizer steps per file per epoch: 1,000 (`batch_size=10` internally)
- **Total optimizer steps per epoch: 20,000**
- **Total WaveNet segments per epoch: 200,000**
- Learning rate: 5e-4 (Adam)
- Focal loss alpha: 0.5, gamma: 2.0

## SIDERIUS Equivalent

To match paper training scale, use:

- `train_portion = 0.2` (20%) + `epochs = 1`, OR
- `train_portion = 0.1` (10%) + `epochs = 2`

Both process approximately 200,000 WaveNet segments per training run, matching the paper. With two epochs, the second option processes approximately 100,000 segments in each epoch.

### Historical baseline (v0 seeds, small_sample_trial)

- `train_portion = 0.1, epochs = 1` → 100,000 WaveNet segments (50% of paper scale)
- This was the setting used for `small_sample_trial_v0` seeds
- Sufficient for hyperparameter exploration but not for reproducing paper scores

### v17 and beyond

- Use `train_portion = 0.2, epochs = 1` or equivalent for formal baseline comparisons
- Agent trial rounds can use lower `train_portion` for speed (e.g. 0.1)

## Notes

- All models in SIDERIUS train a single generalist model across all 20 files (no frequency splitting)
- WaveNet is confirmed by paper authors to not require frequency splitting
- PUNet, FCNet, Transformer, RNN all also use single model in SIDERIUS (architectural decision)
- Transformer uses `segmentation_size=20000` (half of default) due to GPU memory constraints
- Source: `/home/tidmad/TIDMAD/train_nosplit.py` analysis, July 2026
