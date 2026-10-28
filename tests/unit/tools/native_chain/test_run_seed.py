"""Issue #983 S5: the native-chain declaration carries the run seed (Design B).

An explicit seed is rendered into the reviewed shell vector itself, so the
capture equalities ``shell_argv == declaration.shell_arguments()`` and
``iteration_one_argv == current.request.argv`` keep holding. A seedless
declaration keeps its pre-seed bytes, digest and argv (literal pins below,
taken from the pre-S5 code).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.layout import checkout_root
from core.run_invariants import RunInvariants, run_seed_lock_fields, write_run_invariants
from tools.native_chain.models import (
    NativeChainCapture,
    NativeChainDeclaration,
    NativeChainRunBinding,
)
from tools.native_chain.observation import read_locked_seed
from tools.native_chain.review import export_argv

#: Above 2**52, so a float round-trip anywhere on the path would corrupt it.
SEED = 4_503_599_627_370_497

SEEDLESS_JSON = (
    '{"schema_version":"siderius.native-chain/v1","recipe":"native-standard-chain/v1",'
    '"working_directory":"/checkout","run":{"workspace":"/runs/chain","run_name":"chain",'
    '"final_iteration":3},"chain_args":["--task_composition","/project/task.yaml"]}'
)
SEEDLESS_SHA256 = "e6a17b8460076818012ec23dad95d2089b778c4a53862b3991b11d24f3a2eaac"
SEEDLESS_RESUME_ARGV = (
    "--mode",
    "lilab",
    "--workspace",
    "/runs/chain",
    "--run_name",
    "chain",
    "--num_iterations",
    "3",
    "--start_iter",
    "2",
    "--no_auto_resume",
    "--task_composition",
    "/project/task.yaml",
)


def _declaration(run_seed: int | None = None) -> NativeChainDeclaration:
    return NativeChainDeclaration(
        working_directory=Path("/checkout"),
        run=NativeChainRunBinding(
            workspace=Path("/runs/chain"), run_name="chain", final_iteration=3, run_seed=run_seed
        ),
        chain_args=("--task_composition", "/project/task.yaml"),
    )


def test_seedless_declaration_keeps_its_pre_seed_bytes_digest_and_argv():
    """Fails if the absent seed serializes (``"run_seed":null``) or renders a
    flag: every reviewed seedless capture would then stop verifying."""
    declaration = _declaration()
    assert declaration.model_dump_json() == SEEDLESS_JSON
    assert hashlib.sha256(SEEDLESS_JSON.encode()).hexdigest() == SEEDLESS_SHA256
    assert declaration.shell_arguments(start_iteration=2) == SEEDLESS_RESUME_ARGV
    assert NativeChainDeclaration.model_validate_json(SEEDLESS_JSON) == declaration


@pytest.mark.parametrize("start", [1, 3])
def test_explicit_seed_is_rendered_once_on_every_start_iteration(start):
    """Fails if a resumed shell vector (``start_iteration=k``) drops the seed or
    the seed displaces another token: the resumed chain would then no longer
    re-render the reviewed declaration exactly."""
    seeded = _declaration(SEED).shell_arguments(start_iteration=start)
    seedless = list(_declaration().shell_arguments(start_iteration=start))
    flag = seeded.index("--run_seed")
    assert seeded.count("--run_seed") == 1 and seeded[flag + 1] == str(SEED)
    assert list(seeded[:flag] + seeded[flag + 2 :]) == seedless
    assert json.loads(_declaration(SEED).model_dump_json())["run"]["run_seed"] == SEED


@pytest.mark.parametrize("token", ["--run_seed", "--run-seed=5"])
def test_chain_args_cannot_carry_a_run_seed(token):
    """Fails if a seed can bypass the reviewed ``run.run_seed`` binding through
    ``chain_args``, where the capture would not record it as the run seed."""
    with pytest.raises(ValueError, match="protected_chain_control"):
        NativeChainDeclaration(
            working_directory=Path("/checkout"),
            run=NativeChainRunBinding(
                workspace=Path("/runs/chain"), run_name="chain", final_iteration=1
            ),
            chain_args=(token,),
        )


def test_real_shell_export_delivers_the_declared_seed_to_iteration_one(tmp_path):
    """Fails if ``run_chain.sh`` loses the seed between the declaration and the
    native argv that review captures as ``iteration_one_argv``."""

    def exported(run_seed):
        declaration = NativeChainDeclaration(
            working_directory=checkout_root(),
            run=NativeChainRunBinding(
                workspace=tmp_path / "run", run_name="chain", final_iteration=2, run_seed=run_seed
            ),
            chain_args=(
                "--task_composition",
                "configs/task_composition/quickstart.yaml",
                "--data_dir",
                str(tmp_path),
            ),
        )
        return export_argv(declaration, 1, 1048576)

    seeded = exported(SEED)
    assert seeded[seeded.index("--run_seed") + 1] == str(SEED)
    assert "--run_seed" not in exported(None)


def _capture(declaration: NativeChainDeclaration, observed_seed: int | None):
    """A capture whose iteration-1 parameter rows observed ``observed_seed``."""
    root = str(declaration.working_directory)
    request = SimpleNamespace(argv=["--run_seed"], working_directory=root)
    rows = [
        SimpleNamespace(name="run_name", declared_value=declaration.run.run_name),
        SimpleNamespace(name="start_iteration", declared_value=1),
        SimpleNamespace(name="run_seed", declared_value=observed_seed),
    ]
    result = SimpleNamespace(
        outcome="passed", task=object(), task_settings=object(), planner_strategy_identity=""
    )
    environment = SimpleNamespace(
        launch_binding=SimpleNamespace(installation=SimpleNamespace(source_root=root), files=()),
        saved_task_check=SimpleNamespace(
            result=result, declaration=SimpleNamespace(request=request)
        ),
        current_declaration=SimpleNamespace(
            request=request, workspace=str(declaration.run.workspace), parameters=rows
        ),
    )
    source = declaration.model_dump_json()
    return NativeChainCapture.model_construct(
        declaration=declaration,
        source_text=source,
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        declaration_sha256=hashlib.sha256(source.encode()).hexdigest(),
        shell_argv=declaration.shell_arguments(),
        iteration_one_argv=("--run_seed",),
        environment=environment,
        input_files=(),
    )


def test_capture_validator_binds_the_declared_seed_to_the_observed_launch():
    """Accepts an explicit-seed declaration (Design B); fails if a capture whose
    iteration-1 launch resolved no seed, or a different one, still verifies."""
    _capture(_declaration(SEED), SEED).consistent_observations()
    _capture(_declaration(), None).consistent_observations()
    for observed in (None, SEED - 1):
        with pytest.raises(ValueError, match="capture_run_mismatch"):
            _capture(_declaration(SEED), observed).consistent_observations()
    with pytest.raises(ValueError, match="capture_run_mismatch"):
        _capture(_declaration(), SEED).consistent_observations()


def _lock(workspace: Path, run_seed: int | None, source=None) -> None:
    workspace.mkdir()
    write_run_invariants(
        str(workspace),
        RunInvariants(
            resolved_data_scope=[0],
            health_gate_enabled=False,
            health_config_sha256=None,
            runtime_estimator_identity="estimator-v1",
            runtime_policy_identity="policy-v1",
            **run_seed_lock_fields(run_seed, source),
        ),
    )


def test_locked_seed_readback_reports_the_lock_and_never_invents_one(tmp_path):
    """Fails if readback reports a seed the lock does not hold (absent, pre-seed
    or corrupt lock) or misreports the lock's value or provenance. A corrupt
    lock reads as unrecorded instead of making the operation unreadable."""
    assert read_locked_seed(tmp_path / "absent", 65536).run_seed is None
    _lock(tmp_path / "seeded", SEED, "operator")
    seeded = read_locked_seed(tmp_path / "seeded", 65536)
    assert (seeded.run_seed, seeded.run_seed_source) == (SEED, "operator")
    _lock(tmp_path / "legacy", None)
    assert read_locked_seed(tmp_path / "legacy", 65536).model_dump(exclude_none=True) == {}
    (tmp_path / "corrupt").mkdir()
    (tmp_path / "corrupt/run_invariants_lock.json").write_text("{broken")
    assert read_locked_seed(tmp_path / "corrupt", 65536).run_seed is None
