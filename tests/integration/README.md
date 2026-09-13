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

## Bootstrap composition (manual, offline)

From the checkout being tested, synchronize its own frozen environment, then
run exactly this five-case cohort (no real-mode flags):

```bash
env -u PYTHONPATH -u VIRTUAL_ENV uv sync --group dev --frozen
env -u PYTHONPATH -u VIRTUAL_ENV CUDA_VISIBLE_DEVICES= \
  OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  timeout 180 .venv/bin/python -m pytest \
  tests/integration/workflows/test_bootstrap_pseudo.py -q
```

This explicit qualification command owns the bootstrap pseudo-integration
witness; ordinary unit CI does not select it. All five cases must pass without
skips. They exercise the real bounded-probe engine, contention classifier,
observation builder, hash-checked temporary registry and launch guard, using
synthetic task capability, hardware, telemetry and executor timings. No provider,
GPU, dataset, real training or inference is used by this cohort. Environment
installation may need network access; the tests themselves are offline.

Coverage: readiness, subsequent-run priors, promotion of the training bucket
after three distinct consistent observations, busy-context measurement and
idempotent registry writes. Identical inference observations deduplicate rather
than promote. The unnamed pseudo device supplies no occupancy/measurement-validity
evidence. This is not full integration coverage, real GPU qualification or a Gate.

## Declared-composition tuner (manual, offline)

After the same checkout-owned frozen sync above, run these six existing cases:

```bash
env -u PYTHONPATH -u VIRTUAL_ENV CUDA_VISIBLE_DEVICES= \
  OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  timeout 180 .venv/bin/python -m pytest \
  tests/integration/workflows/test_data_scope_tuner_pseudo.py \
  tests/integration/workflows/test_healthgate_ten_collapse_continuation.py -q
```

All six must pass without skips. A temporary declared task supplies fixed-shape
classification, separate train/eval identities and a blocking Health roster.
Real composition, scope projection, round/admission orchestration and
`LocalRecorder` persistence run with finite recording-provider/executor outcomes.
The effect fixture refuses actual provider constructors, workers and process
spawns; no model training, inference, scoring arithmetic or GPU probe executes.
Parent-process RSS instrumentation and temporary record/config writes do occur.

Coverage: four completed collapsed rounds beyond the execution-failure brake;
partial-scope normalization and executor transport; unchanged snapshot/full
scope; explicitly absent and disabled Health with a valid finite candidate;
terminal scope refusal without a later phase or retry. Observe-only actions
never convert a scientifically blocking failed check into a valid candidate.
Ordinary unit CI does not select this manual integration cohort. These supplied
outcomes are not real-LLM, real-Health-arithmetic or physical-workflow evidence;
external-task qualification remains a separate requirement.

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

## Explicit task-boundary persistence and profile transport (manual, offline)

From the checkout being tested, use its frozen environment and run the two
remaining cross-boundary owners together:

```bash
env -u PYTHONPATH -u VIRTUAL_ENV CUDA_VISIBLE_DEVICES= \
  OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  timeout 180 .venv/bin/python -m pytest \
  tests/integration/workflows/test_pr_e_persistence_layout_pseudo.py \
  tests/integration/execute_tools/test_step02a_checkpoint_c_profile_boundary.py -q
```

All fourteen cases must execute without skips. They prove node/workflow
persistence under the shipped Quickstart composition and real subprocess
transport of a test-owned DatasetProfile, task-data-path implementation and
opaque scope. Children run as installed modules from an unrelated temporary
working directory with no `PYTHONPATH` overlay. The cohort uses tiny synthetic
HDF5 files on CPU; it performs no provider call, GPU work or scientific-task
execution.
