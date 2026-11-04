"""Issue #983 S8 (T9): every RNG site and torch process entry in source and examples is
seeded from the run seed or is a listed, reasoned exemption.

The census (``rng_census.py``) walks the whole ``src/**/*.py`` and ``examples/**/*.py`` set with the
AST, resolving import aliases, so a new site cannot hide behind a name. Both
an unlisted site and a stale allowlist entry fail. The synthetic-tree test
proves the census itself sees each defect class it guards against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.core.rng_census import EXAMPLES, SRC, Site, census

_SEEDED_SCOPE = "runs inside seeded_scope or a seeded probe child (validation.probe, S7b)"
_TRAINER = "the trainer seeds the process from its TrainingSeedPlan before this runs (S2)"

#: (module, function, call) -> why the site is seeded or exempt.
ALLOWLIST: dict[Site, str] = {
    Site("agent/data_analysis/generated_program_runner.py", "main", "np.random.seed"): (
        "seeds every generated program from its request seed (S7c)"
    ),
    Site("agent/data_analysis/generated_program_runner.py", "main", "random.seed"): (
        "seeds every generated program from its request seed (S7c)"
    ),
    Site(
        "agent/data_analysis/historical_inference_worker_main.py",
        "run_worker",
        "torch.cuda.manual_seed_all",
    ): "historical inference worker seeds from its declared inference seed",
    Site(
        "agent/data_analysis/historical_inference_worker_main.py", "run_worker", "torch.manual_seed"
    ): ("historical inference worker seeds from its declared inference seed"),
    Site(
        "agent/skills/model_io_probe_skill.py", "build_loss_probe_pair", "torch.randint"
    ): _SEEDED_SCOPE,
    Site(
        "agent/skills/model_io_probe_skill.py", "build_loss_probe_pair", "torch.randn"
    ): _SEEDED_SCOPE,
    Site(
        "agent/skills/model_io_probe_skill.py", "build_model_input", "torch.randint"
    ): _SEEDED_SCOPE,
    Site("agent/skills/model_io_probe_skill.py", "build_model_input", "torch.randn"): _SEEDED_SCOPE,
    Site("core/seeding.py", "generate_run_seed", "secrets.randbelow"): (
        "the single run-seed generator, called only at entry boundaries"
    ),
    Site("core/stub_sandbox.py", "StubSandbox.__init__", "random.Random"): (
        "test stub with a string seed; no scientific output"
    ),
    Site("core/stub_sandbox.py", "StubSandbox.set_run_context", "random.Random"): (
        "test stub with a string seed; no scientific output"
    ),
    Site("execute_tools/process_seeding.py", "apply_process_seeds", "np.random.seed"): "seed owner",
    Site("execute_tools/process_seeding.py", "apply_process_seeds", "random.seed"): "seed owner",
    Site(
        "execute_tools/process_seeding.py", "apply_process_seeds", "torch.manual_seed"
    ): "seed owner",
    Site("execute_tools/process_seeding.py", "dataloader_worker_init", "np.random.seed"): (
        "seed owner: loader worker seed from the loader generator"
    ),
    Site("execute_tools/process_seeding.py", "dataloader_worker_init", "random.seed"): (
        "seed owner: loader worker seed from the loader generator"
    ),
    Site("execute_tools/process_seeding.py", "seeded_scope", "np.random.get_state"): (
        "seed owner: saves the caller's state"
    ),
    Site("execute_tools/candidate_measurement.py", "_input_tensor", "torch.Generator"): (
        "exempt: constant synthetic latency input (seed 0), never training state"
    ),
    Site("execute_tools/candidate_measurement.py", "_input_tensor", "torch.randn"): (
        "exempt: drawn from the local seed-0 generator above"
    ),
    Site("execute_tools/process_seeding.py", "seeded_scope", "np.random.set_state"): (
        "seed owner: restores the caller's state"
    ),
    Site("execute_tools/process_seeding.py", "torch_generator", "torch.Generator"): (
        "seed owner: loader generator from a derived seed"
    ),
    Site("execute_tools/sample_set_builder.py", "build_sample_set", "random.Random"): (
        "seeded with the tuner's derived sampling seed (S3b)"
    ),
    Site(
        "execute_tools/target_standardization.py",
        "fit_training_target_standardization",
        "torch.Generator",
    ): "exempt: constant by design (measurement identity compared across runs)",
    Site(
        "execute_tools/train_engine_sandbox.py",
        "TIDMADDataset.pull_event_from_dir",
        "np.random.randint",
    ): (_TRAINER),
    Site("execute_tools/train_engine_sandbox.py", "_validation_pass", "np.random.get_state"): (
        "validation RNG isolation: saves the training state"
    ),
    Site("execute_tools/train_engine_sandbox.py", "_validation_pass", "np.random.set_state"): (
        "validation RNG isolation: restores the training state"
    ),
    Site("execute_tools/train_engine_sandbox.py", "run_experiment_streaming", "random.Random"): (
        "epoch order stream from TrainingSeedPlan.epoch(k).order (S2)"
    ),
    Site("ml_models/models_sandbox.py", "FullSpectrumGatedConv1d.__init__", "torch.rand"): (
        "model construction: " + _TRAINER + " or " + _SEEDED_SCOPE
    ),
    Site(
        "nodes/ml_code_validator_agent/ml_code_validator_agent.py",
        "_probe_in_process",
        "torch.randint",
    ): _SEEDED_SCOPE,
    Site(
        "nodes/ml_model_implementor/ml_model_implementor.py",
        "_smoke_test_plugin_in_scope",
        "torch.randint",
    ): _SEEDED_SCOPE,
    Site("tools/candidate_console/settings_service.py", "_publish_private", "secrets.token_hex"): (
        "exempt: private file name token, not a scientific draw"
    ),
    Site("tools/candidate_console/workspace.py", "_create_token", "secrets.token_urlsafe"): (
        "exempt: console authentication token, not a scientific draw"
    ),
}

#: Process entries (``__main__.py``, ``*_main.py``, ``main()`` or a ``__main__``
#: guard) that reach torch, directly or through any ``src`` import chain, and do
#: not call a process seeder. Enumerated so a new entry must state its reason.
_CLI = "operator CLI: reaches torch only through imports and builds no model in its own process"
_ORCHESTRATOR = (
    "orchestrator: builds models only in seeded probes (seeded_scope / probe worker, S7b); trai"
    "ners, probe and analysis workers are children that seed their own processes"
)
_MEASUREMENT = "exempt: measurement only; its weights never become scientific output"
ENTRY_ALLOWLIST: dict[str, str] = {
    "agent/data_analysis/historical_inference_worker_main.py": "seeds torch itself from the declared inference seed (run_worker)",
    "agent/data_analysis/reference_packs/build_manifests.py": "build script for reference-pack manifests; builds no model",
    "agent/data_analysis/worker_main.py": "analysis skill worker: no torch model build; its sampling uses the executed sampling seed (S7a)",
    "agent/skills/evaluate_vram_skill/preflight_worker_main.py": _MEASUREMENT
    + " (VRAM pre-flight)",
    "core/native_writer/__main__.py": _CLI,
    "core/runtime_control/checkpoint_identity_worker_main.py": "CPU-only identity reader; no model construction or checkpoint deserialization",
    "core/runtime_control/gpu_measurement_worker_main.py": _MEASUREMENT,
    "core/runtime_control/probe_worker_main.py": _MEASUREMENT + " (bounded runtime probe)",
    "dashboard/main.py": "read-only dashboard server; builds no model",
    "execute_tools/denoising_score_single.py": "scores a fixed deliverable; builds or trains no model",
    "execute_tools/inference_single.py": "exempt: loads a checkpoint and runs in eval(); initialization is overwritten",
    "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py": "tuner CLI entry boundary (S3b): trainers are seeded children",
    "nodes/ml_literature_review/ml_literature_review.py": _CLI,
    "nodes/ml_model_proposal_agent/ml_model_proposal_agent.py": _CLI,
    "nodes/result_interpretation_agent/result_interpretation_agent.py": _CLI,
    "tools/adaptors/__main__.py": _CLI,
    "tools/adaptors/cli.py": _CLI,
    "tools/candidate_console/__main__.py": _CLI,
    "tools/candidate_console/gpu_check.py": "CUDA availability probe (check --gpu): torch.cuda.is_available/device_count and torch.zeros on cuda; no RNG draws, no model build or training",
    "tools/candidate_operations/__main__.py": _CLI,
    "tools/candidate_operations/child.py": _ORCHESTRATOR,
    "tools/candidate_prepare/__main__.py": _CLI,
    "tools/candidate_prepare/child.py": _ORCHESTRATOR,
    "tools/candidate_prepare/reusable_child.py": _ORCHESTRATOR,
    "tools/candidate_worker/__main__.py": _ORCHESTRATOR,
    "tools/candidate_worker/child.py": _ORCHESTRATOR,
    "tools/candidate_worker/loop_resume.py": _ORCHESTRATOR,
    "tools/candidate_worker/unit_child.py": _ORCHESTRATOR,
    "tools/native_chain/__main__.py": _CLI,
    "tools/native_chain/check.py": _CLI,
    "tools/native_chain/iteration.py": _ORCHESTRATOR,
    "tools/native_chain/resume_entry.py": _CLI,
    "tools/orchestration_setup/__main__.py": _CLI,
    "tools/release/build_example_bundle.py": "builds a deterministic example-bundle zip from checkout files; no RNG, torch or model build",
    "tools/run_report/__main__.py": _CLI,
    "tools/run_report/cli.py": _CLI,
    "tools/runtime_replay/__main__.py": _CLI,
    "tools/setup_review/__main__.py": _CLI,
    "tools/setup_review/check_task.py": _CLI,
    "tools/setup_review/composition_child.py": "setup task check: model probes run in the seeded probe worker (S7b)",
    "tools/setup_review/inspect_environment.py": _CLI,
    "tools/setup_review/launch.py": _CLI,
    "tools/setup_review/review.py": _CLI,
    "tools/workspace_sandbox/__main__.py": _CLI,
    "workflows/definition/__main__.py": _CLI,
    "workflows/model_exploration.py": _ORCHESTRATOR,
    "workflows/run_one_iteration.py": _ORCHESTRATOR,
}


EXAMPLE_ALLOWLIST: dict[Site, str] = {
    Site(
        "quickstart/plugins/_quickstart_task.py", "generate_shard", "np.random.default_rng"
    ): "exempt: pinned task dataset generation seed and shard; independent of run sampling",
    Site(
        "quickstart/plugins/_quickstart_task.py",
        "QuickstartTaskDataPath.training_dataset",
        "np.random.default_rng",
    ): "caller supplies TrainingSeedPlan epoch subsample seed; refuses None when sampling",
    Site(
        "quickstart/plugins/_quickstart_task.py",
        "QuickstartTaskDataPath._draw_rows",
        "np.random.default_rng",
    ): "caller supplies run-derived scope sampling seed; refuses None when sampling",
    Site(
        "synthetic_masked_regression/plugins/_masked_task.py",
        "generate_shard",
        "np.random.default_rng",
    ): "exempt: pinned task dataset generation seed and shard; independent of run sampling",
    Site(
        "synthetic_masked_regression/plugins/_masked_task.py",
        "SyntheticMaskedTaskDataPath.training_dataset",
        "np.random.default_rng",
    ): "caller supplies TrainingSeedPlan epoch subsample seed; refuses None when sampling",
    Site(
        "synthetic_masked_regression/plugins/_masked_task.py",
        "SyntheticMaskedTaskDataPath._draw",
        "np.random.default_rng",
    ): "caller supplies run-derived scope sampling seed; refuses None when sampling",
    Site(
        "task_templates/csv_classification/plugins/_csv_task.py",
        "CsvClassificationTaskDataPath._subsample",
        "np.random.default_rng",
    ): "caller supplies scope or epoch seed; refuses None when sampling",
}


@pytest.mark.parametrize(
    ("root", "allowlist", "entry_allowlist"),
    [(SRC, ALLOWLIST, ENTRY_ALLOWLIST), (EXAMPLES, EXAMPLE_ALLOWLIST, {})],
    ids=["src", "examples-including-templates"],
)
def test_every_rng_site_and_process_entry_is_seeded_or_listed(
    root: Path, allowlist: dict[Site, str], entry_allowlist: dict[str, str]
):
    """Fails on an unlisted RNG site or torch process entry (a new unseeded
    path), and on a stale allowlist entry (an exemption that no longer
    matches source, which would otherwise hide the next site there)."""
    sites, entries = census(root)
    assert sorted(sites - allowlist.keys()) == [], "unlisted RNG sites"
    assert sorted(allowlist.keys() - sites) == [], "stale RNG allowlist entries"
    assert sorted(entries - entry_allowlist.keys()) == [], "unseeded torch process entries"
    assert sorted(entry_allowlist.keys() - entries) == [], "stale process-entry allowlist"
    assert all(reason.strip() for reason in (*allowlist.values(), *entry_allowlist.values()))


def test_census_sees_each_guarded_defect_class(tmp_path: Path):
    """Fails if the census is blind to an unseeded DataLoader shuffle, an
    aliased draw, an unseeded torch entry point, a ``secrets`` fallback in a
    data path, or ``hash()`` in execute_tools."""
    data = tmp_path / "execute_tools"
    data.mkdir()
    (data / "loader.py").write_text(
        "from torch.utils.data import DataLoader\n"
        "from numpy.random import default_rng\n"
        "import secrets\n"
        "def build(ds, seed=None):\n"
        "    if seed is None:\n"
        "        seed = secrets.randbits(32)\n"
        "    rng = default_rng(seed)\n"
        "    key = hash(ds)\n"
        "    return DataLoader(ds, shuffle=True), DataLoader(ds, shuffle=True, generator=rng)\n"
    )
    (tmp_path / "worker_main.py").write_text(
        "import torch\n\ndef main():\n    return torch.nn.Linear(2, 2)\n\n"
        "if __name__ == '__main__':\n    main()\n"
    )
    sites, entries = census(tmp_path)
    assert {site.call for site in sites} == {
        "DataLoader(shuffle) without generator",
        "np.random.default_rng",
        "secrets.randbits",
        "hash",
    }
    assert entries == {"worker_main.py"}


def test_entry_rule_follows_torch_through_src_imports(tmp_path: Path):
    """Red-team witness (#1122): an entry that reaches torch only through
    another ``src`` module (and the ``*_main.py`` naming alone) must still be
    caught. Fails if the entry rule only sees a direct ``import torch``."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "model.py").write_text("import torch\n")
    (tmp_path / "pkg" / "relay.py").write_text("from . import model\n")
    (tmp_path / "pkg" / "probe_worker_main.py").write_text("from pkg.relay import model\n")
    (tmp_path / "pkg" / "seeded_main.py").write_text(
        "from pkg import model\nfrom x import seed_process\nseed_process(None)\n"
    )
    (tmp_path / "pkg" / "plain_main.py").write_text("import json\n")
    _sites, entries = census(tmp_path)
    assert entries == {"pkg/probe_worker_main.py"}


@pytest.mark.parametrize("relative", ["quickstart/plugins", "task_templates/new_task/plugins"])
def test_census_sees_new_example_and_template_draws(tmp_path: Path, relative: str):
    """An added example or nested template cannot hide an aliased RNG call."""
    plugin = tmp_path / relative / "data.py"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(
        "from numpy.random import default_rng as rng\ndef draw():\n    return rng()\n"
    )
    sites, _ = census(tmp_path)
    assert sites == {Site(f"{relative}/data.py", "draw", "np.random.default_rng")}
