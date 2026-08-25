"""Step 12 / PR-12d — D5: the Oxford-IIIT Pet pack's complete L4 declarations.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §M `D5`, §A.2 (the B0 per-family
disposition table), §A.3b (the Q-12-4 profile contract) and Q-12d-1.

**This module is D5's evidence OWNER.** Before it, the only Pets "composition"
in the repository was a test fixture whose `dataset_profile` declared
`psd_segment_length`, `segments_per_file`, `sampling_frequency` and
`pets_train_shard_{file_index:04d}.h5` — TIDMAD physics fabricated for a task
that has no PSD segments, no sampling frequency and no HDF5 shards (F-12d-4).
D5 deleted those values rather than carrying them, and shipped the real
declarations the packs' own directory owns.

Two things this module deliberately does NOT claim:

* **Not L4.** Nothing here executes the composed train -> infer -> score path.
  `STATUS.md` says "L4 declarations complete / L4 execution pending" and the
  test below pins that it never says plain L4; promotion is D-FINAL's, on
  `G-12d` evidence.
* **Not secondary-metric executability.** `macro_f1` and `log_loss` COMPOSE
  and bind implementations that claim them, which is what §A.2's cell
  requires of a declaration. Whether a composed run can EVALUATE a secondary
  is a property of the scoring route, not of this pack — see `STATUS.md`
  blockers 1-3.

Every expectation is hardcoded. Reading a direction back out of the
composition under test would pass for any direction, which is the
self-referential shape CLAUDE.md forbids.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "oxford_iiit_pet"
SHIPPED_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "pets.yaml"
MANIFESTS = PACK / "data" / "manifests"

#: §22.9a's FROZEN Track-B terminal metric set, transcribed from the roadmap:
#: golden metric `accuracy` HIGHER, optional terminal `macro_f1` (higher) and
#: `log_loss` (lower). Hardcoded; the composition is asked to agree with it,
#: never consulted to produce it.
DECLARED_PRIMARY = ("accuracy", "higher")
DECLARED_SECONDARIES = (("macro_f1", "higher"), ("log_loss", "lower"))

#: The task's own index domain: the 370 rows of the Gate manifest the shipped
#: composition names. `PetsTaskDataPath._select` validates `target` partitions
#: against `len(rows)`, so rows ARE the domain `DataScope` addresses.
DECLARED_PARTITION_COUNT = 370

#: The exact values the deleted fixture profile declared. Kept as literals so
#: the "deleted, not carried" claim is checkable against what actually
#: existed rather than against a paraphrase of it.
FABRICATED_FIXTURE_VALUES = (
    "psd_segment_length",
    "segments_per_file",
    "sampling_frequency",
    "pets_train_shard_{file_index:04d}.h5",
    "pets_val_shard_{file_index:04d}.h5",
    "storage_dtype",
    "input_channel",
    ".h5",
)

#: What a manifest section may say. Everything here BINDS something; nothing
#: here is a task value. `config` is the one entry that carries the task's own
#: constructor arguments (D1's seam A), and its values are checked separately.
BINDING_KEYS = frozenset(
    {
        "config",
        "declaration",
        "implementation",
        "module",
        "symbol",
        "id",
        "file",
        "none",
        # `model_plugins:` (seam P / DP) is a deliberately DIFFERENT section
        # shape from every other binding: it names a plugin ROOT and the
        # model types that root must produce, not a `config:`-wrapped
        # constructor argument. `dir` is still a REF (composition-relative,
        # resolved the same way `config:` refs are), and `require` is a
        # closed list of TYPE NAMES, not free task prose — so this remains
        # "structure that names a binding", the property this test protects.
        # Step 12 / PR-12d D8a added `model_plugins:` to Pets' shipped
        # manifest (F-12d-2's closure, mirroring DAVIS'), which is the first
        # time this test saw the section at all.
        "dir",
        "require",
    }
)


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    """Health registration is process-global (Step 08b); restore it per test.

    Copied from the established fixture shape in
    ``tests/unit/examples/test_pets_health_family.py`` — composing this pack
    binds its Health family, and a second composition in the same process is
    correctly refused unless the run scope is reset.
    """
    from execute_tools.health_checks import _plugin_binding
    from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY

    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _compose(manifest: pathlib.Path):
    from workflows.task_composition import compose_run_task_bindings

    return compose_run_task_bindings(str(manifest))


def _shipped_manifest_document() -> dict:
    return yaml.safe_load(SHIPPED_MANIFEST.read_text(encoding="utf-8"))


# ======================================================================
# 1. The shipped composition resolves, family by family
# ======================================================================


class TestTheShippedCompositionResolves:
    """§A.2's B0 row for Pets, cell by cell."""

    def test_the_primary_metric_is_accuracy_and_HIGHER(self):
        """Defect caught: the shipped manifest binds a different metric, or
        `accuracy` silently acquires `lower` — which would invert every
        ordering decision the tuner, interpreter and proposer make about this
        run. The pair is hardcoded from §22.9a."""
        composition = _compose(SHIPPED_MANIFEST)
        assert (composition.metric.spec.id, composition.metric.spec.direction) == DECLARED_PRIMARY

    def test_the_secondaries_are_macro_f1_HIGHER_then_log_loss_LOWER(self):
        """Defect caught: a secondary is dropped, gains a wrong direction, or
        the two are declared in an order the report would then render.

        `log_loss` / LOWER is the interesting half. §22.9a chose that identity
        deliberately — a legitimate terminal metric whose name contains
        "loss" — to force D16 to be resolved before the declaration crossed
        the production metric-declaration path. PR-12a C5 removed D16, so a
        metric id is opaque and this composes; a re-introduced lexical rule
        would fail HERE, at the composition edge, which is the only place it
        could ever be re-introduced.
        """
        composition = _compose(SHIPPED_MANIFEST)
        assert tuple((m.spec.id, m.spec.direction) for m in composition.secondary_metrics) == (
            DECLARED_SECONDARIES
        )

    def test_every_secondary_binds_an_implementation_that_CLAIMS_its_id(self):
        """Defect caught: the F-12d-3 mis-binding, re-introduced.

        `EvaluationMetric.IMPLEMENTS` is what an implementation asserts
        INDEPENDENTLY of the declaration handed to it. Three of these
        shipped mis-bound before D4c (`macro_f1` to `AccuracyMetric` among
        them), composing green while computing something else under the right
        label. Asserting only that composition SUCCEEDS would not see it.
        """
        composition = _compose(SHIPPED_MANIFEST)
        for metric in (composition.metric, *composition.secondary_metrics):
            claimed = type(metric).IMPLEMENTS
            assert claimed, f"{type(metric).__name__} claims nothing, so its binding is unprovable"
            assert metric.spec.id in claimed

    def test_the_log_loss_implementation_is_the_PACKS_OWN_file(self):
        """Defect caught: `log_loss` gets bound to a framework metric.

        The pack's implementations are reached ONLY through an explicit
        `file:` ref, which is also what puts their CONTENT digest into the
        semantic fingerprint — an edited pack metric then fails a resume
        closed instead of quietly computing something else. A `module:`
        binding would lose that and would mean production had grown a
        central entry for this task's science.
        """
        composition = _compose(SHIPPED_MANIFEST)
        log_loss = next(m for m in composition.secondary_metrics if m.spec.id == "log_loss")
        assert type(log_loss).__name__ == "PetsLogLossMetric"
        refs = {(p.symbol, p.configured_ref) for p in composition.provenance.plugins}
        assert (
            "PetsLogLossMetric",
            "../../examples/oxford_iiit_pet/plugins/_pets_metrics.py",
        ) in refs

    def test_the_data_path_is_CONFIGURED_with_the_gate_manifest(self):
        """Defect caught: the manifest declares no `config:`, so the composed
        implementation is the bare regime-A instance that can materialize a
        scope it is HANDED but cannot BUILD one — the F-12d-8 failure, which
        surfaced as a by-name refusal at the first tuner attempt.
        """
        from execute_tools.task_data_path import ScopeBuildRequest, resolve_task_scope_capability

        composition = _compose(SHIPPED_MANIFEST)
        assert composition.task_data_path.task_data_path_id == "oxford_iiit_pet"
        capability = resolve_task_scope_capability(composition.task_data_path)
        scope = capability.build_training_scope(
            ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
        )
        assert len(scope.rows) == DECLARED_PARTITION_COUNT

    def test_the_task_config_is_the_PACKS_OWN_and_declares_37_classes(self):
        """Defect caught: a composed Pets run reads TIDMAD's
        `configs/task_config.yaml` — the C-P56-1 family, one surface over. The
        forward contract's class count is the discriminating value: TIDMAD's
        is 256."""
        composition = _compose(SHIPPED_MANIFEST)
        assert composition.forward_contract.num_classes == 37
        assert composition.forward_contract.task_type == "classification"
        assert "37-way" in composition.task_description

    def test_health_binds_the_packs_family_and_interpretation_is_a_NAMED_absence(self):
        """Defect caught: `task_health` resolving `LEGACY_OMITTED` (TIDMAD's
        family) instead of the pack's state-C declaration, or
        `interpretation_blocks` doing the same. Both would be another task's
        science running under this one's name.

        `none: true` is EXPLICIT_NONE — a named absence. Saying nothing at all
        is what resolves TIDMAD's, which is why the manifest states it.
        """
        composition = _compose(SHIPPED_MANIFEST)
        assert composition.task_health_binding == str(PACK / "declared" / "task_health.yaml")
        assert composition.interpretation_blocks is None
        assert composition.proposal_blocks is None
        assert composition.implementor_blocks is None


# ======================================================================
# 2. The profile is Q-12-4-honest — asserted field by field
# ======================================================================


class TestTheProfileCarriesNoTIDMADPhysics:
    """§A.3b. The contract is `partition_count` + an OPAQUE `topology` + the
    two REQUIRED declared file sets, and nothing else."""

    def test_the_profile_declares_exactly_the_generic_identity_contract(self):
        """Defect caught: a profile that satisfies the schema by carrying the
        LEGACY wire form's `dataset`/`channels`/`encoding` sections — the
        shape that forced the old fixture to invent a `sampling_frequency`
        for an image classifier. `declares_tidmad_topology` is the membership
        test that names it; it is never inferred from catching an exception.
        """
        from execute_tools.dataset_config import declares_tidmad_topology

        profile = _compose(SHIPPED_MANIFEST).dataset_profile
        assert profile.partition_count == DECLARED_PARTITION_COUNT
        assert not declares_tidmad_topology(profile)
        assert set(profile.topology) & {"dataset", "channels", "encoding"} == set()

    @pytest.mark.parametrize("fabricated", FABRICATED_FIXTURE_VALUES)
    def test_no_fabricated_value_survives_anywhere_in_the_shipped_declaration(self, fabricated):
        """Acceptance criterion 3, grep-proven field by field rather than
        "looks generic".

        Defect caught: a fabricated TIDMAD-physical value is carried into the
        shipped profile — by copy-editing the fixture, or by a later author
        reaching for the familiar section names. The needles are the literal
        strings the deleted fixture declared, so this fails on exactly the
        thing F-12d-4 condemned and not on a paraphrase of it.
        """
        assert fabricated not in (PACK / "declared" / "dataset_profile.json").read_text(
            encoding="utf-8"
        )

    def test_the_two_REQUIRED_declared_file_sets_are_present_and_legal(self):
        """Defect caught: an author treats the Q-12-4 profile as "TIDMAD's
        fields minus the physical ones" and omits the file sets, which are
        REQUIRED with no default — precisely so a new task cannot silently
        inherit another task's frequency-band representatives.

        Pets declares `[0]` for both. `health_peek_files` is genuinely
        consumed: this pack's Health provider materializes its view from
        deliverable slot 0. `anchor_selection_files` is NOT — Pets' scope
        capability refuses the `anchors` strategy by name, so the declaration
        exists to satisfy a non-empty framework requirement and index 0 is
        the honest minimum rather than an invented set of representatives.
        """
        profile = _compose(SHIPPED_MANIFEST).dataset_profile
        assert profile.anchor_selection_files == [0]
        assert profile.health_peek_files == [0]

    def test_the_topology_is_OPAQUE_and_the_framework_declines_physical_geometry(self):
        """Defect caught: seam B regressing — a generic reader treating an
        absent physical geometry as an exception rather than a DECLARED
        absence. The topology carries Pets' real facts (144px crop, 37
        classes); the framework must decline to interpret them rather than
        raise from inside `tidmad_topology`.
        """
        from execute_tools.deliverable_spec import derive_run_deliverable_spec
        from nodes.ml_hyperparameter_tune_agent.scope_acquisition import (
            TaskTopologyUnavailableError,
            project_attempt_topology_facts,
        )

        profile = _compose(SHIPPED_MANIFEST).dataset_profile
        assert profile.topology["class_cardinality"] == 37
        assert profile.topology["input_tensor"]["shape"] == [3, 144, 144]
        assert derive_run_deliverable_spec(profile) is None
        facts = project_attempt_topology_facts(profile)
        assert facts.declares_physical_geometry is False
        with pytest.raises(TaskTopologyUnavailableError):
            facts.require_physical_dataset("a purpose that needs physical geometry")


# ======================================================================
# 3. `configs/task_composition/pets.yaml` is a POINTER (Q-12d-1)
# ======================================================================


class TestTheShippedManifestIsAPointerOnly:
    """Q-12d-1: task-owned declarations co-locate with the pack, and the
    `configs/` manifest "carries no second copy of task semantics"."""

    def test_every_resolved_source_lives_inside_the_pack(self):
        """Defect caught: a family whose declaration was copied into
        `configs/` — a second copy free to drift from the pack's, which is
        the whole failure Q-12d-1 rules against. Reads the RESOLVED
        provenance rather than the manifest text, so a `..`-walk that lands
        outside the pack is caught too.
        """
        composition = _compose(SHIPPED_MANIFEST)
        pack = str(PACK) + "/"
        for family, source in composition.provenance.source_paths.items():
            assert source.startswith(pack), f"{family} resolves outside the pack: {source}"
        for plugin in composition.provenance.plugins:
            assert plugin.absolute_path.startswith(pack)

    def test_no_manifest_section_carries_a_key_that_is_not_a_BINDING(self):
        """Defect caught: a task value inlined into `configs/` — a threshold,
        a description, a class count — which would make the manifest a second
        authority instead of a pointer. Unknown keys are refused by
        composition, but a key that composition ACCEPTS and that carries
        semantics (there is exactly one, `config:`) would pass unnoticed, so
        the check is the whitelist plus the ref-shape assertion below.
        """
        for section, payload in _shipped_manifest_document().items():
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                unexpected = sorted(set(entry) - BINDING_KEYS)
                assert not unexpected, (
                    f"section {section!r} declares non-binding key(s) {unexpected}"
                )

    def test_every_task_owned_config_value_is_a_manifest_REF(self):
        """Defect caught: the seam-A `config:` mapping — the one place a
        manifest may carry the task's own constructor arguments — used to
        smuggle a task VALUE. Every entry is a `{ref: ...}` envelope, which
        is the task saying "resolve this against the manifest" rather than
        the framework learning what `manifest_path` (or `eval_manifest_path`)
        means.

        UPGRADED at Step 12 / PR-12d (F-12d-17, D-12d-36): the manifest gained
        a second key when the eval scope stopped falling back to the training
        one. The count moved from ONE entry to the EXACT set below, so a
        third key smuggled in later still trips this.
        """
        config = _shipped_manifest_document()["task_data_path"]["config"]
        assert config == {
            "manifest_path": {
                "ref": "../../examples/oxford_iiit_pet/data/manifests/gate2_train.csv"
            },
            "eval_manifest_path": {
                "ref": "../../examples/oxford_iiit_pet/data/manifests/gate2_validation.csv"
            },
        }
        assert all(set(entry) == {"ref"} for entry in config.values()), (
            "every task-owned config value must be a {ref: ...} envelope, nothing else"
        )


# ======================================================================
# 4. Checksum coverage — F-12d-5
# ======================================================================


def test_every_committed_manifest_csv_is_checksum_pinned():
    """F-12d-5. Defect caught: a manifest a Gate reads has no integrity pin.

    Before D5 only the three IDENTITY manifests were pinned while the
    `gate2_*.csv` subsets a Gate actually consumes were not, so a corrupted
    or hand-edited Gate subset was undetectable. The set equality is the
    claim: a new committed CSV that nobody pins fails here rather than being
    silently uncovered.
    """
    from tools.example_packs._common import parse_sha256sums, sha256_of_file

    pinned = parse_sha256sums((MANIFESTS / "SHA256SUMS").read_text(encoding="utf-8"))
    present = {p.name for p in MANIFESTS.glob("*.csv")}
    assert set(pinned) == present
    assert {"gate2_train.csv", "gate2_validation.csv", "gate2_final.csv"} <= present
    for name, digest in pinned.items():
        assert sha256_of_file(MANIFESTS / name) == digest, f"{name} differs from its pin"


def test_regenerating_the_identity_manifests_cannot_DROP_the_gate_pins(tmp_path):
    """The reason the writers re-pin the whole directory, made executable.

    Defect caught: `write_pack` pins only the names IT wrote, so anyone
    regenerating the identity manifests silently deletes the Gate subsets'
    coverage — leaving a `SHA256SUMS` that still looks complete. Fails if the
    writer goes back to a fixed name list.
    """
    from tools.example_packs._common import parse_sha256sums
    from tools.example_packs.oxford_iiit_pet import Manifests, parse_manifest_csv, write_pack

    manifests = tmp_path / "data" / "manifests"
    manifests.mkdir(parents=True)
    for scope in ("train", "validation", "final"):
        (manifests / f"gate2_{scope}.csv").write_text(
            "image_id,class_index,official_class_id,scope\n", encoding="utf-8"
        )

    def _rows(scope: str):
        return parse_manifest_csv((MANIFESTS / f"{scope}.csv").read_text(encoding="utf-8"))

    write_pack(
        tmp_path,
        Manifests(train=_rows("train"), validation=_rows("validation"), final=_rows("final")),
    )
    pinned = set(parse_sha256sums((manifests / "SHA256SUMS").read_text(encoding="utf-8")))
    assert {"gate2_train.csv", "gate2_validation.csv", "gate2_final.csv"} <= pinned


# ======================================================================
# 5. STATUS honesty — the operator ruling
# ======================================================================


def test_status_claims_L4_only_together_with_its_witness_and_its_non_claims():
    """D-FINAL: promoted, and the promotion must carry what backs it.

    This test used to assert the OPPOSITE — that STATUS said "declarations
    complete, execution pending" — because the pack must never promote itself
    on the strength of its DECLARATIONS. ``G-12d`` executed the composed path,
    so the assertion is inverted rather than deleted and the invariant is
    unchanged: *a maturity claim must never outrun its evidence.*

    Defect caught: a bare "L4" heading with nothing behind it. The reader who
    acts on a maturity label needs the run that earned it and, more sharply,
    the things it still does not cover — this pack's composed run fired ZERO
    health gates, so "L4" alone would imply a Health demonstration on the
    composed path that has not happened.
    """
    text = (PACK / "STATUS.md").read_text(encoding="utf-8")
    maturity = next(line for line in text.splitlines() if line.startswith("## Maturity"))
    assert "L4" in maturity and "EXECUTION PENDING" not in maturity

    assert "run_output_g12d_pets_track1.json" in text
    assert "2a5940a49d3709c2fb6d867b15807c0fb0dda5ce2d3b2d58f229583fb74478fc" in text
    assert "does NOT claim" in text
    assert "health_gate_results` is `[]`" in text
    assert "No scientific claim" in text


def test_status_names_the_blockers_that_keep_the_secondaries_unevaluated():
    """Defect caught: `log_loss` ships as a declaration while STATUS reads as
    though a composed run would compute it.

    The pack's own codec writes `image_id,predicted_class_index` — arg-max
    labels with no distribution — and `PetsLogLossMetric` refuses that
    payload BY NAME. STATUS has to say so, because a reader comparing the
    declared metric set against a terminal report would otherwise conclude
    the run had silently dropped a metric.
    """
    text = (PACK / "STATUS.md").read_text(encoding="utf-8")
    assert "DECLARED but not yet COMPUTABLE" in text
    assert "predicted_class_index" in text


# ======================================================================
# 6. Negative falsifiers — a broken manifest fails CLOSED, by family name
# ======================================================================


def _manifest_copy(tmp_path: pathlib.Path, mutate) -> pathlib.Path:
    """The shipped manifest, copied to `configs/task_composition/` so its
    `../..` refs keep resolving, with one mutation applied."""
    document = _shipped_manifest_document()
    mutate(document)
    target = SHIPPED_MANIFEST.parent / f"_d5_negative_{tmp_path.name}.yaml"
    target.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
    return target


def test_a_missing_family_fails_closed_NAMING_the_family(tmp_path):
    """Defect caught: a family a manifest forgets resolving its legacy
    default instead of refusing — which for `task_health` means TIDMAD's
    roster and thresholds evaluating a Pets deliverable.

    The family NAME must be in the message: "composition failed" sends an
    operator to read the whole manifest, and the whole point of the required
    section set is that the answer is one word.
    """
    from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

    target = _manifest_copy(tmp_path, lambda doc: doc.pop("task_health"))
    try:
        with pytest.raises(TaskCompositionError, match="task_health"):
            compose_run_task_bindings(str(target))
    finally:
        target.unlink()


def test_a_secondary_duplicating_the_PRIMARY_id_is_refused(tmp_path):
    """Defect caught: two metrics answering to `accuracy` in one run.

    A report carrying the id twice cannot say which arithmetic produced which
    number, and a consumer keyed by metric id would silently take whichever
    came last. Refusing at composition is the only place this is cheap.
    """
    from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

    def _duplicate(doc):
        doc["secondary_metrics"] = doc["secondary_metrics"] + [
            {
                "declaration": "../../examples/oxford_iiit_pet/declared/metric_accuracy.json",
                "implementation": {
                    "module": "execute_tools.evaluation_metric",
                    "symbol": "AccuracyMetric",
                },
            }
        ]

    target = _manifest_copy(tmp_path, _duplicate)
    try:
        with pytest.raises(TaskCompositionError, match="accuracy"):
            compose_run_task_bindings(str(target))
    finally:
        target.unlink()


# ======================================================================
# 7. Integration — a composed Pets run reaches the tuner with its own metric
# ======================================================================


def test_a_composed_pets_run_reaches_the_tuner_with_ITS_OWN_metric_and_direction(tmp_path):
    """The shipped declarations drive the real `run_workflow`, under pseudo
    execution.

    Defect caught: the shipped manifest composes in isolation but something
    on the loop's own path substitutes an assumed metric — the C-P56-1 family.
    Only a drive through `run_workflow` can see that, because the substitution
    would happen between composition and the tuner's input.

    **Not claimed**: no training, inference or scoring runs here, and this is
    not evidence of contrast-track L4. The agents are mocked exactly as the
    Step-10 C6 closure mocks them; what is asserted is what the generic path
    HANDS the tuner.
    """
    from unittest.mock import patch

    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
    from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
    from tests.unit.workflows.test_model_exploration import (
        _make_implementor_output,
        _make_interpretation_output,
        _make_proposal_output,
        _make_tune_output,
        _make_validator_output,
    )
    from workflows.model_exploration import run_workflow
    from workflows.run_config import WorkflowLaunchConfig
    from workflows.task_composition import bind_run_task_composition

    composition = _compose(SHIPPED_MANIFEST)

    # A seed stamped with THIS composition — an unstamped or TIDMAD-stamped
    # one is correctly refused (R-11-9 / P2a), which would test the refusal
    # rather than the orchestration.
    agent_dir = tmp_path / "data" / "punet" / "v1" / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "run_output_v1_agent.json").write_text(
        HyperparamTuningOutput(
            run_name="v1",
            model_type="punet",
            file_index=0,
            status="completed",
            task_composition_fingerprint=composition.semantic_fingerprint,
            completed_rounds=1,
            total_attempts=1,
            best_exp_id="punet_v1_001",
            best_denoising_score=0.5,
            best_formal_denoising_score=0.5,
            best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
            all_records=[
                {
                    "exp_id": "punet_v1_001",
                    "status": "success",
                    "model_type": "punet",
                    "timestamp": "2026-01-01 00:00:00",
                    "file_index": 0,
                    "params": {"model_config": {}, "train_config": {}, "loss_config": {}},
                    "results": {"denoising_score": 0.5},
                    "denoising_score": 0.5,
                }
            ],
            started_at="2026-01-01 00:00:00",
            finished_at="2026-01-01 01:00:00",
            metric_spec=composition.metric.spec,
        ).model_dump_json(indent=2)
    )

    seen: dict = {}
    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):

        def _interp(inp):
            seen["interp"] = inp
            return _make_interpretation_output()

        def _tune(inp):
            seen["tune"] = inp
            out = _make_tune_output(model_type=inp.model_type, score=0.5)
            out.metric_spec = composition.metric.spec
            return out

        MockInterp.return_value.run.side_effect = _interp
        MockPropose.return_value.run.return_value = _make_proposal_output("pets_cand_1")
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = _tune

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            results = run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=1,
                ),
                workspace=str(tmp_path / "ws"),
                run_name="d5_pets",
                task_composition=composition,
            )

    assert len(results) == 1
    assert seen["tune"].task_composition_ref is not None
    # The interpreter is handed the run's OWN spec, hardcoded against §22.9a.
    assert (seen["interp"].metric_spec.id, seen["interp"].metric_spec.direction) == (
        DECLARED_PRIMARY
    )
    lock = json.loads((tmp_path / "ws" / "run_invariants_lock.json").read_text(encoding="utf-8"))
    assert lock["task_composition_fingerprint"] == composition.semantic_fingerprint
