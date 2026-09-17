"""`examples/quickstart/` — pack integrity, composability, and landed-boundary pins.

Every test names the defect only it catches and how it fails when the
behaviour breaks (CLAUDE.md test rule).

HISTORY OF THE THREE BOUNDARY PINS. On the pre-12d base this module carried
three DELIBERATE pins against the then-current composition boundary
(unknown `model_plugins` key · F-12d-4 model_io refusal · seam-A `config:`
silently ignored). PR-12d landed (master squash `84d74280`) and all three
flipped exactly as designed — the recorded signal that executed the pack's
post-12d checklist (README §7). Each pin below is the RE-SCOPED landed-
behaviour successor of one of them, and each carries a non-vacuity plant so
a refusal-shaped pin cannot go green for the wrong reason.

All composition here runs inside ``run_registration_scope`` so the
process-global task-data-path registry is returned to its inherited roster
after each test (PR-12bc C1 overlay).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from execute_tools.model_output_retention import apply_output_retention
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    ScopeBuildRequest,
    ValidationScopeError,
    declares_scope_capability,
)
from execute_tools.task_registration_scope import run_registration_scope
from tests.unit.examples import test_pack_governance as governance
from workflows.task_composition import (
    TaskCompositionError,
    bind_run_task_composition,
    compose_run_task_bindings,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "quickstart"
SHIPPED_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"


def _load_pack_module() -> Any:
    """Execute the pack's task plugin from its file, the composition way."""
    path = PACK / "plugins" / "_quickstart_task.py"
    spec = importlib.util.spec_from_file_location("quickstart_pack_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["quickstart_pack_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _shipped_manifest_variant(tmp_path: Path, transform) -> Path:
    """Write a separately registered variant of the shipped synthetic task.

    The shipped refs are ``../../``-rooted against its own directory;
    external refs resolve the checkout's unchanged model/config assets. The
    task adapter itself is copied with a distinct fixture id: rebinding the
    shipped id through an absolute plugin ref would conflict with an inherited
    relative-ref registration before the model/config rule under test runs.
    Registry refusal remains intact; this variant is explicitly a separate task.
    """
    text = SHIPPED_MANIFEST.read_text(encoding="utf-8").replace("../../", f"{REPO_ROOT}/")
    adapter = tmp_path / "quickstart_variant_task.py"
    adapter.write_text(
        (PACK / "plugins" / "_quickstart_task.py")
        .read_text(encoding="utf-8")
        .replace(
            'QUICKSTART_TASK_ID = "quickstart_tabular"',
            'QUICKSTART_TASK_ID = "quickstart_variant_fixture"',
        ),
        encoding="utf-8",
    )
    text = text.replace(
        f"{REPO_ROOT}/examples/quickstart/plugins/_quickstart_task.py", adapter.name
    ).replace("id: quickstart_tabular", "id: quickstart_variant_fixture")
    variant = tmp_path / "quickstart_variant.yaml"
    variant.write_text(transform(text), encoding="utf-8")
    return variant


def test_variant_preserves_an_inherited_shipped_registration(tmp_path: Path) -> None:
    """An existing task must not mask the variant's actual model/config checks."""
    from execute_tools.task_data_path import registered_content_identity

    with run_registration_scope():
        shipped = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        identity = registered_content_identity("quickstart_tabular")
        repeated = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        assert repeated.semantic_fingerprint == shipped.semantic_fingerprint
        variant = _shipped_manifest_variant(
            tmp_path, lambda text: text.replace("train_shards: [0, 1]", "train_shards: [0]")
        )
        composed = compose_run_task_bindings(str(variant))
        assert composed.task_data_path_id == "quickstart_variant_fixture"
        scope = composed.task_data_path.build_training_scope(
            ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
        )
        assert {row.shard for row in scope.rows} == {0}
        assert registered_content_identity("quickstart_tabular") == identity


@pytest.fixture(scope="module")
def pack_module() -> Any:
    return _load_pack_module()


@pytest.fixture()
def bundle(pack_module: Any, tmp_path: Path) -> dict[str, str]:
    return pack_module.materialize_run_bundle(PACK, tmp_path / "bundle")


# ---------------------------------------------------------------------------
# provenance: the checkout under test is the checkout being tested
# ---------------------------------------------------------------------------


def test_composition_authority_resolves_from_this_checkout() -> None:
    """Defect caught: the venv's editable SIDERIUS install (site-packages
    ``__editable__.siderius*.pth``) shadows this checkout, so every other
    assertion in this module would be validating ANOTHER clone's code — a
    live incident during this pack's construction: a scratchpad-launched
    script imported `/home/yuema137/SIDERIUS` (a different branch) and
    produced evidence against the wrong tree. Fails by naming both paths."""
    import workflows.task_composition as tc

    resolved = Path(tc.__file__).resolve()
    assert resolved == REPO_ROOT / "src/workflows" / "task_composition.py", (
        f"workflows.task_composition resolved to {resolved}, not this checkout "
        f"({REPO_ROOT}). The interpreter is importing a DIFFERENT clone (an "
        "editable install?); every result in this test session describes that "
        "clone, not the one under test. Run pytest from the checkout root."
    )


# ---------------------------------------------------------------------------
# governance: the pack under the repo guards a targeted run would skip
# ---------------------------------------------------------------------------


def test_pack_satisfies_the_examples_governance_guards() -> None:
    """Defect caught: a quickstart edit reintroduces a governance-tripping
    file while only the quickstart's own tests are run locally — the
    repo-wide guards live in another module a targeted run does not execute.
    Asserted through the governance module's OWN functions so the rule cannot
    drift from this copy.

    Post-12d specifics this covers: the committed
    ``declared/task_config.yaml`` is legitimate exactly because the SHIPPED
    ``configs/task_composition/quickstart.yaml`` binds it — this asserts the
    file IS in the guard's bound set AND that guard (a) passes with the
    exemption applied. Fails by naming the offending file."""
    assert PACK.is_dir()
    bound = governance._composition_bound_task_configs(REPO_ROOT)
    committed_config = (PACK / "declared" / "task_config.yaml").resolve()
    assert committed_config in bound, (
        "declared/task_config.yaml is NOT bound by any shipped composition "
        "manifest — guard (a)'s exemption does not cover it, so it is a "
        "refused parallel copy. Did configs/task_composition/quickstart.yaml "
        "lose its task_config.config ref?"
    )
    offenders = [
        (path, key)
        for path, key in governance._yaml_parallel_copies(REPO_ROOT / "examples", bound)
        if PACK in path.parents
    ]
    assert offenders == [], f"guard (a) offenders inside the quickstart pack: {offenders}"
    stray = [
        p
        for p in governance._python_files_under(PACK)
        if not governance._is_sanctioned_plugin_source(p.relative_to(REPO_ROOT).as_posix())
    ]
    assert stray == [], f"`.py` outside examples/quickstart/plugins/: {stray}"
    for doc in governance.REQUIRED_PACK_DOCS:
        assert (PACK / doc).is_file(), f"quickstart lacks {doc}"
    status = (PACK / "STATUS.md").read_text(encoding="utf-8")
    assert governance.MATURITY_LEVEL.search(status), "STATUS.md names no L0-L4 level"
    readme = (PACK / "README.md").read_text(encoding="utf-8")
    assert governance.ROADMAP_DOC.split("/")[-1] in readme
    assert "§22.9" in readme or "§22.23" in readme


def test_plant_unbound_task_config_yaml_is_detected(tmp_path: Path) -> None:
    """PLANT: proves the landed guard (a) still catches this pack's exact
    hazard shape — a copy of the committed task config that NO shipped
    manifest binds (the default empty bound set is "nothing is exempt").
    Without this, the 12d re-scope could silently widen into "any task
    config under examples/ is fine". Fails if the guard goes blind to
    either key or starts exempting unbound files."""
    mirror = tmp_path / "examples" / "quickstart" / "declared"
    mirror.mkdir(parents=True)
    planted = mirror / "task_config.yaml"
    planted.write_text(
        (PACK / "declared" / "task_config.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    offenders = governance._yaml_parallel_copies(tmp_path / "examples")
    assert offenders == [(planted, "task_description"), (planted, "forward_contract")]


# ---------------------------------------------------------------------------
# composability on the landed base (the executable half)
# ---------------------------------------------------------------------------


def test_shipped_manifest_composes_with_the_declared_values() -> None:
    """Defect caught: ANY family of the pack drifts out of composability on
    the landed base — a declaration the loader refuses, a plugin whose symbol
    vanishes, an id mismatch, a broken ref in the SHIPPED
    ``configs/task_composition/quickstart.yaml`` (which is the exact file the
    README tells a user to launch with). Fails with the composition's own
    fail-closed message."""
    with run_registration_scope():
        composition = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        assert composition.task_data_path_id == "quickstart_tabular"
        assert composition.metric.spec.id == "accuracy"
        assert composition.metric.spec.direction == "higher"
        assert composition.dataset_profile.partition_count == 4
        # `none: true` composes to 08b's EXPLICIT_NONE named absence, whose
        # string value is pinned here (the fingerprint hashes it as such).
        assert str(composition.task_health_binding) == "explicit_none"
        assert composition.deliverable_naming is not None
        assert composition.deliverable_naming.prefix == "quickstart_predictions"
        pinned = sorted(
            ref.configured_ref.rsplit("/", 1)[-1] for ref in composition.provenance.plugins
        )
        # Landed PR-12d: the model_plugins resolution pins the resolved model
        # plugin's content digest beside the task/metric plugins, so an edited
        # reference model fails a resume closed too.
        assert pinned == [
            "_quickstart_metrics.py",
            "_quickstart_task.py",
            "quickstart_reference_mlp.py",
        ]
        # The declared profile facts and the plugin constants must not drift:
        # both state the same task, in two artifacts.
        pack_module = _load_pack_module()
        profile = json.loads((PACK / "declared" / "dataset_profile.json").read_text())
        assert profile["anchor_selection_files"] == list(composition.task_data_path._anchor_shards)
        roles = profile["topology"]["roles"]
        assert tuple(roles["train_shards"]) == pack_module.TRAIN_SHARDS
        assert roles["validation_shard"] == pack_module.VALIDATION_SHARD
        assert roles["final_eval_shard"] == pack_module.FINAL_EVAL_SHARD


def test_landed_pin_model_plugins_section_composes_and_requires(tmp_path: Path) -> None:
    """LANDED-BOUNDARY PIN (successor of the pre-12d unknown-key refusal pin,
    which flipped when `model_plugins` became a known `_MANIFEST_KEYS`
    member). Defect caught: the pack's model-plugin route into a composed
    run degrades — the shipped section stops resolving
    `quickstart_reference_mlp`, or the `require:` contract stops being
    enforced (a missing plugin would then surface as a mid-run failure
    instead of a composition refusal).

    Non-vacuity plant: a `require:` naming a type the directory does not
    produce must REFUSE at composition, by name."""
    with run_registration_scope():
        composition = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        binding = composition.model_plugins
        assert binding is not None, "shipped manifest lost its model_plugins binding"
        assert tuple(binding.required_model_types) == ("quickstart_reference_mlp",)
    variant = _shipped_manifest_variant(
        tmp_path,
        lambda text: text.replace(
            "require: [quickstart_reference_mlp]", "require: [no_such_model_type]"
        ),
    )
    with run_registration_scope(), pytest.raises(TaskCompositionError) as refusal:
        compose_run_task_bindings(str(variant))
    message = str(refusal.value)
    assert message.startswith("model_plugins:"), message
    assert "no_such_model_type" in message, (
        f"the require-contract refusal stopped naming the missing type:\n{message}"
    )


def test_landed_pin_model_io_task_config_composes_f12d4_fixed(tmp_path: Path) -> None:
    """LANDED-BOUNDARY PIN (successor of the pre-12d F-12d-4 refusal pin,
    which flipped when the class-count read became profile-shape-aware).
    Defect caught: a composed non-TIDMAD task config declaring `model_io`
    stops composing — the F-12d-4 regression returning — or the derived
    authority stops deriving (num_classes / input shape no longer owned by
    the structured contract).

    Non-vacuity plant: `model_io` PLUS a contradicting authored prose field
    must still REFUSE (the contract validator is alive, so this pin's green
    is not "validation stopped happening")."""
    with run_registration_scope():
        composition = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        contract = composition.forward_contract
        assert contract.model_io is not None, "declared/task_config.yaml lost model_io"
        assert contract.num_classes == 2  # DERIVED from the class axis, not authored
        assert "4" in contract.input_shape and "float32" in contract.input_shape
    committed = (PACK / "declared" / "task_config.yaml").read_text(encoding="utf-8")
    contradicted = tmp_path / "task_config_contradicted.yaml"
    contradicted.write_text(committed + "  num_classes: 3\n", encoding="utf-8")
    variant = _shipped_manifest_variant(
        tmp_path,
        lambda text: text.replace(
            f"{REPO_ROOT}/examples/quickstart/declared/task_config.yaml", str(contradicted)
        ),
    )
    with run_registration_scope(), pytest.raises(TaskCompositionError) as refusal:
        compose_run_task_bindings(str(variant))
    assert "contradicting prose" in str(refusal.value), (
        f"the model_io-vs-prose contradiction stopped refusing:\n{refusal.value}"
    )


def test_landed_pin_section_keys_refused_and_config_reaches_constructor(
    tmp_path: Path,
) -> None:
    """LANDED-BOUNDARY PIN (successor of the pre-12d SILENT-IGNORE pin: on
    the old base a `task_data_path.config:` was dropped with no warning —
    the one manifest hazard the top-level key check could not see). PR-12d
    closed both halves, and this pins them:

    (i) an unknown SECTION key now REFUSES by name
        (`_refuse_unknown_section_keys` — the plant is the misspelling
        `configs:` for `config:`, the exact hazard the old pin recorded);
    (ii) the seam-A `config:` mapping now REACHES the constructor — proven
        counterfactually: `train_shards: [0]` yields a scope over shard [0],
        where the pre-12d composer silently produced [0, 1].

    Fails (i) if section keys go back to being ignored, (ii) if the config
    envelope stops being applied."""
    misspelled = _shipped_manifest_variant(
        tmp_path,
        lambda text: text.replace("  config:\n", "  configs:\n"),
    )
    with run_registration_scope(), pytest.raises(TaskCompositionError) as refusal:
        compose_run_task_bindings(str(misspelled))
    message = str(refusal.value)
    assert "section 'task_data_path' declares unknown key(s) ['configs']" in message, message

    narrowed = _shipped_manifest_variant(
        tmp_path,
        lambda text: text.replace("train_shards: [0, 1]", "train_shards: [0]"),
    )
    with run_registration_scope():
        composition = compose_run_task_bindings(str(narrowed))
        scope = composition.task_data_path.build_training_scope(
            ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
        )
        shards = sorted({row.shard for row in scope.rows})
    assert shards == [0], (
        f"training shards resolved to {shards} despite config train_shards: [0] — "
        "the seam-A config: mapping no longer reaches the constructor."
    )


# ---------------------------------------------------------------------------
# generator determinism — the dataset identity IS the seed + the pins
# ---------------------------------------------------------------------------


def test_generator_is_deterministic_and_matches_the_committed_pins(pack_module: Any) -> None:
    """Defect caught: the generator or its committed identity drifts — a
    "reproducible" dataset that regenerates different bytes, or pins edited
    without the generator (and vice versa). Fails by naming the shard whose
    sha moved. Same-process re-render equality also catches hidden global
    RNG state."""
    committed = json.loads((PACK / "declared" / "data_manifest.json").read_text())
    assert committed["seed"] == pack_module.GENERATOR_SEED
    assert committed["shards"] == pack_module.SHARD_COUNT
    assert committed["rows_per_shard"] == pack_module.ROWS_PER_SHARD
    for shard in range(pack_module.SHARD_COUNT):
        first = pack_module.render_shard_csv(shard)
        assert first == pack_module.render_shard_csv(shard), f"shard {shard} not deterministic"
        digest = hashlib.sha256(first.encode("utf-8")).hexdigest()
        name = pack_module.shard_filename(shard)
        assert digest == committed["sha256"][name], (
            f"{name} regenerated with sha {digest}, but declared/data_manifest.json "
            f"pins {committed['sha256'][name]} — generator and pins must move together."
        )


def test_materializer_refuses_a_drifted_generator(pack_module: Any, tmp_path: Path) -> None:
    """PLANT for the materializer's self-check: a pack whose committed pins
    disagree with the regenerated bytes must REFUSE to write a run bundle
    (the drift fails at materialization, not downstream in a run). Fails if
    the sha verification is dropped or goes soft."""
    fake_pack = tmp_path / "pack"
    (fake_pack / "declared").mkdir(parents=True)
    (fake_pack / "plugins").mkdir()
    for name in ("dataset_profile.json", "metric_accuracy.json", "task_config.yaml"):
        (fake_pack / "declared" / name).write_text((PACK / "declared" / name).read_text())
    manifest = json.loads((PACK / "declared" / "data_manifest.json").read_text())
    manifest["sha256"]["shard_0000.csv"] = "0" * 64
    (fake_pack / "declared" / "data_manifest.json").write_text(json.dumps(manifest))
    for name in ("_quickstart_task.py", "_quickstart_metrics.py"):
        (fake_pack / "plugins" / name).write_text((PACK / "plugins" / name).read_text())
    with pytest.raises(ValueError, match="disagree with declared/"):
        pack_module.materialize_run_bundle(fake_pack, tmp_path / "out")


# ---------------------------------------------------------------------------
# executable components (the pack's L2 claims), CPU-only
# ---------------------------------------------------------------------------


def test_scope_construction_and_canonical_codec(pack_module: Any) -> None:
    """Defect caught: the TaskScopeCapability sibling drifts — a selection
    strategy resolving the wrong shards, an eval scope leaking a train
    shard, a subset_ref silently accepted, or a serialize/deserialize pair
    that stops being canonical (which would break the identity chain the
    framework digests). Fails on the specific property."""
    impl = pack_module.QuickstartTaskDataPath()
    assert declares_scope_capability(impl)
    snapshot = ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
    train = impl.build_training_scope(snapshot)
    assert sorted({r.shard for r in train.rows}) == [0, 1]
    assert len(train.rows) == 128
    anchors = impl.build_training_scope(
        ScopeBuildRequest(round_kind="trial", selection_strategy="anchors", portion=1.0)
    )
    assert sorted({r.shard for r in anchors.rows}) == [0]
    target = impl.build_training_scope(
        ScopeBuildRequest(
            round_kind="formal",
            selection_strategy="target",
            portion=0.5,
            seed=11,
            target_partitions=(1,),
        )
    )
    assert sorted({r.shard for r in target.rows}) == [1]
    assert len(target.rows) == 32  # floor(64 * 0.5)
    with pytest.raises(ValueError, match="never leak into a training scope"):
        impl.build_training_scope(
            ScopeBuildRequest(
                round_kind="formal",
                selection_strategy="target",
                portion=1.0,
                target_partitions=(2,),
            )
        )
    with pytest.raises(ValueError, match="no subset vocabulary"):
        impl.build_training_scope(
            ScopeBuildRequest(
                round_kind="formal",
                selection_strategy="snapshot",
                portion=1.0,
                subset_ref="0-1",
            )
        )
    evaluation = impl.build_eval_scope(snapshot)
    assert sorted({r.shard for r in evaluation.rows}) == [pack_module.VALIDATION_SHARD]
    payload = impl.serialize_scope(evaluation)
    assert impl.serialize_scope(impl.deserialize_scope(payload)) == payload
    with pytest.raises(ValueError, match="declares kind"):
        impl.deserialize_scope(json.dumps({"kind": "pets_rows", "rows": []}))


def test_datasets_materialize_and_validation_fails_closed(
    pack_module: Any, bundle: dict[str, str]
) -> None:
    """Defect caught: the data-path methods stop honouring their contracts —
    a training subsample ignoring portion/ceiling, tensors with the wrong
    dtype/shape for the declared forward contract, or the validation
    exact-materialization obligation going soft (padding / silently
    accepting a row the disk does not hold). Fails on the specific
    contract."""
    impl = pack_module.QuickstartTaskDataPath()
    scope = impl.build_training_scope(
        ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
    )
    dataset = impl.training_dataset(
        scope,
        EpochSamplingParams(
            data_dir=bundle["data_dir"], epoch_seed=3, train_portion=0.25, max_samples=20
        ),
    )
    assert len(dataset) == 20  # floor(128*0.25)=32, then the ceiling
    features, label = dataset[0]
    assert tuple(features.shape) == (4,) and str(features.dtype) == "torch.float32"
    assert label.shape == () and str(label.dtype) == "torch.int64"

    eval_scope = impl.build_eval_scope(
        ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
    )
    validation = impl.validation_dataset(
        eval_scope, EvalMaterializationParams(data_dir=bundle["data_dir"])
    )
    assert len(validation) == 64

    forged = pack_module.QuickstartScope(
        rows=(pack_module.QuickstartScopeRow(sample_id="s2r999", shard=2, row=999, label=0),)
    )
    with pytest.raises(ValidationScopeError, match="did not materialize exactly"):
        impl.validation_dataset(forged, EvalMaterializationParams(data_dir=bundle["data_dir"]))
    with pytest.raises(ValidationScopeError, match="zero rows"):
        impl.validation_dataset(
            pack_module.QuickstartScope(rows=()),
            EvalMaterializationParams(data_dir=bundle["data_dir"]),
        )


def test_deliverable_codec_and_metric_outcomes(bundle: dict[str, str], tmp_path: Path) -> None:
    """Defect caught: the write/read codec pair or the metric arithmetic
    drifts — the declared naming no longer names the artifact (landed
    `input_identity` keyword), the payload does not round-trip, oracle
    predictions stop scoring 1.0, an all-wrong deliverable stops scoring
    0.0, or a missing artifact stops REFUSING (NotScoreableResult) and
    starts scoring. Run inside the composed binding of the SHIPPED manifest,
    so the declared `deliverable:` template is the one exercised."""
    with run_registration_scope():
        composition = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=bundle["data_dir"]):
            impl = composition.task_data_path
            eval_scope = impl.build_eval_scope(
                ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
            )
            oracle = {row.sample_id: row.label for row in eval_scope.rows}
            out_dir = tmp_path / "deliverables"
            request = dict(exp_id="exp0", run_name="demo", model_type="quickstart_reference_mlp")
            impl.write_deliverable(
                oracle, DeliverableWriteRequest(output_dir=str(out_dir), **request)
            )
            name = impl.deliverable_name(**request)
            assert name == ("quickstart_predictions_quickstart_reference_mlp_demo_exp0_0000.json")
            assert (out_dir / name).is_file()
            decoded = impl.read_evaluation_payload(
                EvaluationReadRequest(deliverable_dir=str(out_dir), **request)
            )
            assert decoded == oracle
            deliverable = {0: str(out_dir / name)}
            perfect = composition.metric.evaluate(
                deliverable, evaluation_payload=decoded, task_scope=eval_scope, data_dir=None
            )
            assert type(perfect).__name__ == "MetricResult" and perfect.scalar == 1.0
            wrong = {key: 1 - value for key, value in oracle.items()}
            zero = composition.metric.evaluate(
                deliverable, evaluation_payload=wrong, task_scope=eval_scope, data_dir=None
            )
            assert zero.scalar == 0.0
            refused = composition.metric.evaluate(
                {0: str(out_dir / "does_not_exist.json")},
                evaluation_payload=decoded,
                task_scope=eval_scope,
                data_dir=None,
            )
            assert type(refused).__name__ == "NotScoreableResult"
            assert refused.verdict.failures[0].requirement == "completeness"


def test_quickstart_inventory_retires_only_this_attempt(tmp_path: Path, pack_module: Any) -> None:
    """The framework example must declare its output lifetime, not rely on a core glob."""
    task = pack_module.QuickstartTaskDataPath()
    request = EvaluationReadRequest(
        deliverable_dir=str(tmp_path),
        run_name="run-a",
        exp_id="attempt-a",
        model_type="model-a",
    )
    own = tmp_path / task.deliverable_name(
        model_type=request.model_type,
        run_name=request.run_name,
        exp_id=request.exp_id,
    )
    neighbor = tmp_path / task.deliverable_name(
        model_type=request.model_type,
        run_name=request.run_name,
        exp_id="attempt-b",
    )
    own.write_text("{}", encoding="utf-8")
    neighbor.write_text("{}", encoding="utf-8")

    receipt = apply_output_retention(task=task, request=request, retain_model_outputs=False)

    assert receipt.status == "completed"
    assert [item.relative_path for item in receipt.artifacts] == [own.name]
    assert not own.exists()
    assert neighbor.exists()


def test_deliverable_codec_accepts_the_composed_childs_positional_outputs(
    bundle: dict[str, str], tmp_path: Path
) -> None:
    """Regression for the 2026-08-25 live chain run (final-witness batch,
    item A): `execute_tools/generic_inference.py::run_generic_inference`
    hands the codec UNPAIRED per-sample logit tensors IN SCOPE ROW ORDER
    with `request.task_scope` populated (seam C / B7 — pairing is
    task-owned), and this pack's codec refused the list
    (`ValueError: ... must be a mapping ... got list.` → `error_inference`),
    killing the only attempt that had trained. Fails, if the codec regresses
    to mapping-only, with exactly that live ValueError; the strict-length
    arm fails by NOT raising when a truncated output list would silently
    mis-pair every later sample."""
    import torch

    with run_registration_scope():
        composition = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=bundle["data_dir"]):
            impl = composition.task_data_path
            eval_scope = impl.build_eval_scope(
                ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
            )
            # One [2]-logit tensor per row, argmax alternating 0/1 by index —
            # hand-computed expectation, never read back from the thing under
            # test.
            logits = [
                torch.tensor([1.0, -1.0]) if index % 2 == 0 else torch.tensor([-1.0, 1.0])
                for index in range(len(eval_scope.rows))
            ]
            out_dir = tmp_path / "deliverables"
            request = dict(exp_id="exp1", run_name="demo", model_type="quickstart_reference_mlp")
            impl.write_deliverable(
                logits,
                DeliverableWriteRequest(output_dir=str(out_dir), task_scope=eval_scope, **request),
            )
            decoded = impl.read_evaluation_payload(
                EvaluationReadRequest(deliverable_dir=str(out_dir), **request)
            )
            expected = {
                row.sample_id: (0 if index % 2 == 0 else 1)
                for index, row in enumerate(eval_scope.rows)
            }
            assert decoded == expected
            with pytest.raises(ValueError, match="refusing to mis-pair"):
                impl.write_deliverable(
                    logits[:-1],
                    DeliverableWriteRequest(
                        output_dir=str(out_dir), task_scope=eval_scope, **request
                    ),
                )
            with pytest.raises(ValueError, match="must be a mapping"):
                impl.write_deliverable(
                    logits,
                    DeliverableWriteRequest(output_dir=str(out_dir), **request),
                )


def test_composed_generic_inference_persists_a_scoreable_metric_result(
    bundle: dict[str, str], tmp_path: Path
) -> None:
    """Close the quickstart's deterministic composed-scoring gap.

    Defect caught: component tests for the codec and metric both pass while
    the production generic inference handoff fails to persist an artifact the
    composed metric can score. A constant class-zero model gives a
    hand-computed 37/64 accuracy on the pinned evaluation shard; reordering,
    dropping samples, naming the wrong artifact, decoding another format, or
    bypassing the declared metric makes this assertion fail.
    """
    import torch

    from execute_tools.generic_inference import run_generic_inference

    class ConstantZeroClassifier(torch.nn.Module):
        def forward(self, inputs):
            return torch.tensor([1.0, -1.0], dtype=inputs.dtype).repeat(len(inputs), 1)

    with run_registration_scope():
        composition = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=bundle["data_dir"]):
            impl = composition.task_data_path
            eval_scope = impl.build_eval_scope(
                ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
            )
            out_dir = tmp_path / "composed_scoring"
            out_dir.mkdir()
            identity = {
                "exp_id": "exp2",
                "run_name": "deterministic",
                "model_type": "constant_zero_classifier",
            }
            outcome = run_generic_inference(
                data_path=impl,
                task_scope=eval_scope,
                model=ConstantZeroClassifier(),
                device=torch.device("cpu"),
                data_dir=bundle["data_dir"],
                batch_size=7,
                write_request=DeliverableWriteRequest(output_dir=str(out_dir), **identity),
            )
            assert outcome.samples == 64
            assert outcome.batches == 10
            artifact = out_dir / outcome.deliverable_name
            assert artifact.is_file()
            payload = impl.read_evaluation_payload(
                EvaluationReadRequest(deliverable_dir=str(out_dir), **identity)
            )
            result = composition.metric.evaluate(
                {0: str(artifact)},
                evaluation_payload=payload,
                task_scope=eval_scope,
                data_dir=bundle["data_dir"],
            )
            assert type(result).__name__ == "MetricResult"
            assert result.scalar == 0.578125


# ---------------------------------------------------------------------------
# docs sync — the copied command is the tested command; HTML mirrors the ipynb
# ---------------------------------------------------------------------------


def _notebook_section_headings() -> list[str]:
    notebook = json.loads((PACK / "quickstart.ipynb").read_text(encoding="utf-8"))
    headings: list[str] = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "markdown":
            continue
        for line in "".join(cell["source"]).splitlines():
            if line.startswith("## "):
                headings.append(line[3:].strip())
    return headings


def test_notebook_html_readme_and_command_stay_in_sync() -> None:
    """Defect caught: the three renderings of one tutorial drift — the
    hand-authored HTML stops mirroring the notebook's section sequence, or
    the README's copy-paste launch command stops being the SAME command the
    notebook's launch cell shows (the 12e §V.2 principle: the command a user
    copies is the command the pack pins). Fails by naming the missing
    heading / token."""
    headings = _notebook_section_headings()
    assert len(headings) >= 14, f"notebook lost sections: {headings}"
    html = (PACK / "quickstart.html").read_text(encoding="utf-8")
    for heading in headings:
        assert f"<h2>{heading}</h2>" in html, (
            f"quickstart.html is out of sync with the notebook: missing <h2>{heading}</h2>"
        )
    readme = (PACK / "README.md").read_text(encoding="utf-8")
    notebook_text = (PACK / "quickstart.ipynb").read_text(encoding="utf-8")
    for token in (
        "scripts/launch/run_chain.sh",
        "--mode lilab",
        "--task_composition configs/task_composition/quickstart.yaml",
        "--data_dir",
        "--llm_config configs/llm/openai_tiered_pro.json",
        "--healthgate_mode blocking",
        "--result_authority diagnostic",
        "--num_iterations 1",
        "--max_rounds 1",
    ):
        assert token in readme, f"README launch command lost {token!r}"
        assert token in notebook_text, f"notebook launch cell lost {token!r}"
    command = re.search(r"```bash\n[^`]*bash scripts/launch/run_chain\.sh[^`]+```", readme)
    assert command, "README carries no bash launch command block"
