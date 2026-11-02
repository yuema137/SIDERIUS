# CPU trainer subprocess witnesses

`test_step02a_checkpoint_c_profile_boundary.py` owns the shared synthetic HDF5
fixture (`boundary_workspace`), explicit training argv (`_training_argv`) and
child environment/launch helpers (`_child_env`, `_run`).
`test_step03_checkpoint_c_subprocess.py` reuses those owners for its cardinality
and dtype witnesses; it supplies only the model-I/O contract and attempt name.

The fixture copies `tests/fixtures/step10_p1/fourth_task`, writes its tiny dataset
profile and selects `tests/helpers/synthetic_training_data_path.py:TwoFamilyDataPath`.
The adapter owns HDF5 decoding and scope deserialization. Its training scope
selects file 0, two 4096-sample segments, and 1024-sample rows. The fixture's
`write_scope_artifact` call publishes the serialized scope and returns its digest.

The real child receives `--task_manifest`, `--task_data_path_id`,
`--task_scope_ref`, and `--task_scope_digest`, in addition to model, loss, train
and dataset-profile configuration. The interpreter is the current checkout's
`sys.executable`, launched with `-m execute_tools.train_engine_sandbox` and no
`PYTHONPATH` overlay. Step-03 launches from its temporary sandbox directory; its
import witness checks that package resolution still points into this checkout.
No missing-binding refusal is bypassed or monkeypatched.

Step-03 asserts a saved 256-class output projection with the compatible contract,
with no model-I/O flag, and with input dtype narrowed to int64. A contradictory
16-class contract must report `DatasetContradictionError`; unsupported bfloat16
must report `UnsupportedModelInputDtypeError`, rather than an earlier binding
failure. Invalid JSON must fail, and the import witness establishes checkout
ownership. These tests cover transport and consumption, not scientific quality
or arbitrary class alphabets; in-process cardinality contrasts have separate
unit witnesses.

Run the directory with this checkout's frozen environment and GPUs hidden as
shown in [README.md](README.md). GPU-specific tests skip; the trainer witnesses
use CPU and synthetic files only. CI does not select the integration directory,
so report its local command, exit status and summary separately from Actions.
