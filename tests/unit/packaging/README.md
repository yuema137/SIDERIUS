# tests/unit/packaging

`test_package_resources.py` checks source `pyproject.toml` package-data
declarations against runtime reader paths, including a negative case for a
removed prompt declaration. The installed-package witness is a separate
check; this test does not build/install a wheel or run a campaign.

## Focused route

`.venv/bin/python -m pytest tests/unit/packaging/test_package_resources.py -q`

Owner: `pyproject.toml` package-data declarations and source resource trees.
This test does not build/read a wheel or inspect installed origin; use the
separate integration witness for that boundary.
