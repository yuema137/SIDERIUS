# `examples/quickstart/plugins/`

Manifest-bound task behavior lives here: [`_quickstart_task.py`](_quickstart_task.py)
generates/materializes the seeded shards and supplies scope/deliverable
adapters; [`_quickstart_metrics.py`](_quickstart_metrics.py) owns accuracy;
[`quickstart_reference_mlp.py`](quickstart_reference_mlp.py) is
the required reference model plugin. The leading-underscore modules are
reachable through explicit `file:` references in the manifest, not discovery.

These are example-owned plugins, not framework task authority. Generated data
and run artifacts stay in a caller workspace. Validate the pack through
[`test_quickstart_pack.py`](../../../tests/unit/examples/test_quickstart_pack.py).
