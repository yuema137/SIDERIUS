# src/tools/ci

`.venv/bin/python -m tools.ci` is the maintained CI harness; [`__main__.py`](__main__.py) selects bulk
or sensitive lanes, `execution.py` runs shards, and `preflight.py` verifies
the checkout/provenance. See [`docs/testing/ci_parity.md`](../../../docs/testing/ci_parity.md)
and focused preflight tests under [`test_preflight.py`](../../../tests/unit/tools/ci/test_preflight.py).

See [the parent guide](../README.md) for child ownership and the focused validation route.
