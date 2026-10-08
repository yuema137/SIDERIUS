# Quickstart: a small synthetic classification task

This example shows how a task package supplies data access, a model contract
and a metric to SIDERIUS. It classifies 256 seeded four-feature vectors into two
classes. Data preparation and component checks run on CPU without downloads or
API keys. A real research-chain launch makes provider calls.

Browse [quickstart.ipynb](quickstart.ipynb) or its [HTML rendering](quickstart.html)
for the worked example. Saved live-run excerpts are dated historical evidence;
your current checkout and a new run can produce different results.

## Prepare the synthetic data

Install the exact checkout with `uv sync --group dev --frozen`. From its root:

```bash
cd examples/quickstart
../../.venv/bin/python -c "
from pathlib import Path
import importlib.util, sys, os
spec = importlib.util.spec_from_file_location('qs', 'plugins/_quickstart_task.py')
qs = importlib.util.module_from_spec(spec); sys.modules['qs'] = qs
spec.loader.exec_module(qs)
ws = Path(os.environ.get('SIDERIUS_QUICKSTART_WORKSPACE', str(Path.home() / 'siderius_quickstart_workspace')))
print(qs.materialize_run_bundle(Path.cwd(), ws))
"
```

This writes four hash-checked CSV shards under
`$SIDERIUS_QUICKSTART_WORKSPACE/data`, or under
`$HOME/siderius_quickstart_workspace/data` when that variable is unset.
Return to the repository root before the next command:

```bash
cd ../..
```

## Preview a research run

```bash
WS="${SIDERIUS_QUICKSTART_WORKSPACE:-$HOME/siderius_quickstart_workspace}"

bash scripts/launch/run_chain.sh \
    --mode lilab \
    --workspace "$WS/chain" \
    --run_name quickstart_v1 \
    --num_iterations 1 \
    --max_rounds 1 \
    --task_composition configs/task_composition/quickstart.yaml \
    --data_dir "$WS/data" \
    --healthgate_mode blocking \
    --result_authority diagnostic \
    --llm_config configs/llm/openai_tiered_pro.json \
    --dry-run
```

The preview prints child commands. It does not execute or qualify training.
Before removing `--dry-run`, follow the
[credential and launch procedure](../../docs/getting-started/first-run.md).
The example declares no Health family, so it demonstrates workflow mechanics
without claiming scientific validity or useful model quality.

## What to inspect

The task uses 128 training rows and 64 evaluation rows. The model input is
four floating-point values; its output contains two class scores. Inference
writes the declared prediction artifact and the metric computes accuracy.

The deterministic inference-to-scoring test produces the expected
`37/64 = 0.578125` for its constant predictor. Earlier live chains demonstrated
training and recovery but did not produce a scored tuner record. The
[status reference](STATUS.md) distinguishes those witnesses from current
capability; [provenance](PROVENANCE.md) records their revisions and limitations.

## Understand and adapt the package

| Part | Read next |
| --- | --- |
| Scientific declarations | [declared/](declared/README.md) |
| Data, metric and model implementations | [plugins/](plugins/README.md) |
| Manifest selecting them | [quickstart.yaml](../../configs/task_composition/quickstart.yaml) |
| Your own task | [Task definition reference](../../docs/guides/define-a-task.md) |

Indexed artifact naming and task-owned artifact naming are different contracts;
follow the task reference rather than copying a plugin method blindly.
The historical example-governance design is
[siderius_generic_framework_upgrade.md](../../docs/design/siderius_generic_framework_upgrade.md)
§22.23. Current checks live in `tests/unit/examples/test_quickstart_pack.py`.
