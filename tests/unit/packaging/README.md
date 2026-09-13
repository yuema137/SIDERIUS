# tests/unit/packaging

`test_package_resources.py` checks source `pyproject.toml` package-data
declarations against runtime reader paths, including a negative case for a
removed prompt or Health-policy declaration. The installed-package witness is a separate
check; this test does not build/install a wheel or run a campaign.

## Focused route

`.venv/bin/python -m pytest tests/unit/packaging/test_package_resources.py -q`

Owner: `pyproject.toml` package-data declarations and source resource trees.
This test does not build/read a wheel or inspect installed origin; use the
separate integration witness for that boundary.

`tests/integration/installed_health_policy_witness.py` is the focused manual
offline owner for the sdist-built wheel with physically unavailable checkouts.
It is not collected by pytest CI; see the integration README for its environment
and receipt contract. The default Health YAML is package-data, while optional
checkout policy variants and task manifests remain excluded.
