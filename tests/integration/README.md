# tests/integration

Cross-boundary integration coverage is grouped by API, protocol, node, runner,
scoring, skill, and workflow seams; inspect markers before opting into effects.

## Child routes

- [dashboard](dashboard/README.md) — FastAPI TestClient API checks.
- [execute_tools](execute_tools/README.md), [nodes](nodes/README.md), and
  [protocols](protocols/README.md) — typed cross-boundary seams.
- [prompt_templates](prompt_templates/README.md), [runner](runner/README.md),
  and [scoring](scoring/README.md) — rendering, launch bookkeeping, and
  historical scoring compatibility.
- [skills](skills/README.md) and [workflows](workflows/README.md) — effectful
  or pseudo campaign paths; inspect their markers before running.
- `agent/` and `health_checks/` contain only `__init__.py` placeholders today;
  they have no standalone integration implementation.

Dashboard `test_api.py` uses FastAPI TestClient with synthetic local JSON and
does not need a server. Other dual-mode families default to recording doubles;
real provider or training paths require `--real-llm`/`--real-training` (the
deprecated `--real-api-call` enables both). Collection alone is not a live-run
claim. See the [tests map](../README.md).

## Installed Health policy (manual, offline)

`installed_health_policy_witness.py` owns wheel-resource/filesystem acceptance,
not training or ordinary pytest CI. Build an sdist, build a wheel from it, and
install the exact lock plus that wheel into a new external environment. Stage
this driver and a pre-change policy oracle externally; never stage a checkout
policy to supply the default. Run with Python `-I`, neutral CWD, at most two
numerical-library threads and `timeout 120`. Use a mount namespace to hide each
validated source checkout (including its `README.md` and `pyproject.toml`), with
only the fresh witness directory writable. A chdir or import monkeypatch is
not equivalent. Missing mount support is NOT RUN, not a passed portability test.

Arguments: `--workspace`, `--expected-root` (installed site-packages),
`--baseline` (pre-change JSON body/hash/plugin receipt), and repeatable
`--unavailable-root`. The driver records eight package origins, hidden paths,
default/explicit equivalence, observe comparison, named empty Health, invalid
inputs, body-immutable resume and cold damaged-default independence. Damaged
resource probes alter only the disposable installation and restore its bytes.
No network/provider/GPU/training calls. The broader `installed_package_witness.py`
now also uses the packaged default, but its CPU lifecycle is a separate claim.
