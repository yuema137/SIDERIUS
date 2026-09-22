# Scoped target standardization

`train_config.target_standardization` defaults to `none`. Existing training
and plain state-dict loading retain their behavior. Opt into
`training_pool_global` for a regressor (or hybrid in regression mode) with a
floating-target objective and matching prediction/target shapes.

The native scoped trainer fits one scalar mean and population standard
deviation over all target elements in the selected training pool, using
streaming float64 moments. It calls only the task's training-dataset interface,
with the existing opaque training scope and `train_portion=1.0`; it never
expands that scope or reads validation/test targets for fitting. An explicit
qualification row ceiling is preserved. This is a **global scalar** transform,
not independent transforms for differently scaled output channels. Tasks with
heterogeneous target units should not enable it without a suitable policy.

The base model predicts standardized values. The framework wraps its output as
`prediction = mean + scale * base_output` and applies the inverse transform
to both predictions and targets before calling the configured loss. Validation
uses that same criterion. Final inference/scoring use the original task units.
Do not also implement an inverse target transform in the generated plugin.

Fitting is a real extra data pass; input tensors may be read as part of the
task dataset interface. It is included in the attempt's elapsed budget/setup,
checks allocation while reading, and reports `fit_seconds`, training rows,
target elements, mean and scale. Non-finite, empty or constant targets refuse
this policy before optimizer steps rather than inventing a scale. The loss
fingerprint includes the fitted transform so objectives with different units
are not treated as the same configured loss.

The model state dict contains the affine buffers and a format marker alongside
base-model weights. Ordinary inference and certified historical inference use
the same strict loader; no training dataset is needed to reconstruct outputs.
Certified artifacts additionally bind the transform implementation hash.
Old artifacts omit that optional field and retain their prior identity.

`target_standardization` is persisted in training results and experiment
records, with a validated receipt. This feature neither chooses an architecture
nor enables early stopping. It composes with best-validation checkpoint
selection: fitted statistics stay fixed while the best complete model state
is retained.
