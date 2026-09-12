# `examples/synthetic_masked_regression/plugins/`

Explicit manifest-bound plugins own this example's behavior:
[`_masked_task.py`](_masked_task.py) handles deterministic data, scope, and
deliverable transport; [`_masked_metrics.py`](_masked_metrics.py) computes
valid-row MSE/MAE; [`masked_mse_loss.py`](masked_mse_loss.py) owns masked
training semantics; [`masked_reference_mlp.py`](masked_reference_mlp.py) is
the reference regressor; and [`_masked_health_views.py`](_masked_health_views.py)
projects valid predictions for the declared Health provider.

These files are task plugins, not generic framework implementations. Their
composition and offline behavior are covered by
[`test_synthetic_masked_regression_pack.py`](../../../tests/unit/examples/test_synthetic_masked_regression_pack.py);
generated data and run artifacts stay outside the checkout.
