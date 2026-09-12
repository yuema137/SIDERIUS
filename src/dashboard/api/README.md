# src/dashboard/api

Read-only HTTP boundary: [`router.py`](router.py) defines workspace/result
routes and [`models.py`](models.py) defines response schemas, wired by
`dashboard.main`. It consumes a configured data-source adapter and never
controls execution; focused checks are in `tests/unit/dashboard/`.

See [the parent guide](../README.md) for child ownership and the focused validation route.
