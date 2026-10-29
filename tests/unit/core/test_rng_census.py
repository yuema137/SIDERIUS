"""Issue #983 S8 (T9): every RNG site and torch process entry in ``src`` is
seeded from the run seed or is a listed, reasoned exemption.

The census (``rng_census.py``) walks the whole ``src/**/*.py`` set with the
AST, resolving import aliases, so a new site cannot hide behind a name. Both
an unlisted site and a stale allowlist entry fail. The synthetic-tree test
proves the census itself sees each defect class it guards against.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.core.rng_census import Site, census

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
    Site("core/sandbox_executor.py", "StubSandbox.__init__", "random.Random"): (
        "test stub with a string seed; no scientific output"
    ),
    Site("core/sandbox_executor.py", "StubSandbox.set_run_context", "random.Random"): (
        "test stub with a string seed; no scientific output"
    ),
    Site("core/seeding.py", "generate_run_seed", "secrets.randbelow"): (
        "the single run-seed generator, called only at entry boundaries"
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

#: torch-importing process entries that do not call a process seeder.
ENTRY_ALLOWLIST: dict[str, str] = {
    "agent/data_analysis/historical_inference_worker_main.py": (
        "seeds torch itself from the declared inference seed (run_worker)"
    ),
    "core/runtime_control/gpu_measurement_worker_main.py": (
        "exempt: measurement only; its weights never become scientific output"
    ),
    "execute_tools/inference_single.py": (
        "exempt: loads a checkpoint and runs in eval(); initialization is overwritten"
    ),
}


def test_every_rng_site_and_process_entry_is_seeded_or_listed():
    """Fails on an unlisted RNG site or torch process entry (a new unseeded
    path), and on a stale allowlist entry (an exemption that no longer
    matches source, which would otherwise hide the next site there)."""
    sites, entries = census()
    assert sorted(sites - ALLOWLIST.keys()) == [], "unlisted RNG sites"
    assert sorted(ALLOWLIST.keys() - sites) == [], "stale RNG allowlist entries"
    assert sorted(entries - ENTRY_ALLOWLIST.keys()) == [], "unseeded torch process entries"
    assert sorted(ENTRY_ALLOWLIST.keys() - entries) == [], "stale process-entry allowlist"
    assert all(reason.strip() for reason in (*ALLOWLIST.values(), *ENTRY_ALLOWLIST.values()))


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
