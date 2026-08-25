"""Step 12 / PR-12d — D6: the DAVIS pack's complete L4 DECLARATIONS.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §M `D6`, §A.2 (per-family disposition)
and §A.3b (the Q-12-4 profile contract as landed).

DAVIS is the track whose shape is unlike both TIDMAD and Pets: dense
continuous output, a **LOWER**-is-better primary, **mixed-direction**
secondaries, and — the part that stresses the generic identity hardest — a
temporal rank whose input and target extents DIFFER (8 context frames in, 4
predicted frames out).

**Declarations only.** Nothing here executes DAVIS; the real run is `G-12d`'s.
What this module owns is that everything a composed DAVIS run needs is
DECLARED, that the declared values are the ones §22.9a froze, and that the
fabricated TIDMAD-physical values F-12d-4 condemned are GONE rather than
tidied.

**STATUS.md is deliberately not L4 here** (operator ruling): declarations
complete, execution pending. Promotion belongs to D-FINAL, after the Gate.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "davis_future_prediction"
DECLARED = PACK / "declared"
MANIFESTS = PACK / "data" / "manifests"
MANIFEST_DIR = REPO_ROOT / "configs" / "task_composition"
SHIPPED = MANIFEST_DIR / "davis.yaml"

#: TIDMAD's shipped composition identity, which D6 must not disturb. A pinned
#: LITERAL, captured before this commit: recomputing it here would compare the
#: composition authority to itself and pass for any value.
TIDMAD_COMPOSITION_FINGERPRINT = "9125bf587fea5bae1493800e9b50bafbb63164ff72ec1bfe3b08520ae1e72aac"

#: The §22.9a Track-C freeze, transcribed as literals. Read back from the
#: composition these would prove nothing; hardcoded, they are the contract.
PRIMARY = ("mse", "lower")
SECONDARIES = (("psnr", "higher"), ("mae", "lower"))

#: Every TIDMAD-physical name the fabricated fixture profile used to carry
#: (`tests/fixtures/step10_p1/davis/dataset_profile.json` before D6). A task
#: with clips has no PSD segments, no sampling frequency and no HDF5 shards.
FABRICATED = (
    "psd_segment_length",
    "segments_per_file",
    "sampling_frequency",
    "num_files",
    "training_file_pattern",
    "validation_file_pattern",
    "storage_dtype",
    "value_offset",
    "num_classes",
    "input_channel",
    "target_channel",
    ".h5",
)


@pytest.fixture(scope="module")
def composition():
    """The SHIPPED manifest, composed through the production entry point.

    Not a fixture copy: D6's whole claim is about the declarations an operator
    and the Gate will actually point `--task_composition` at.
    """
    return compose_run_task_bindings(str(SHIPPED))


@pytest.fixture
def variant(tmp_path):
    """Compose an edited copy of the shipped manifest, in ITS OWN directory.

    Refs resolve relative to the manifest, so a variant written anywhere else
    would exercise relaxed resolution rules rather than production's.
    """
    written: list[pathlib.Path] = []

    def _compose(text: str):
        path = MANIFEST_DIR / f"_d6_variant_{len(written)}_{tmp_path.name}.yaml"
        path.write_text(text, encoding="utf-8")
        written.append(path)
        return compose_run_task_bindings(str(path))

    try:
        yield _compose
    finally:
        for path in written:
            path.unlink(missing_ok=True)


# ======================================================================
# 1. The three directions, as DECLARED values
# ======================================================================


class TestTheDeclaredMetricSet:
    """Acceptance: primary `mse`/LOWER, secondaries `psnr`/higher, `mae`/lower."""

    def test_the_primary_is_mse_and_LOWER(self, composition):
        """DAVIS is the only track whose primary is minimized.

        Fails when the declaration is edited to `higher`, or when the primary
        is rebound to another id — either of which would make every ordering
        site in the tuner rank DAVIS backwards while every test that read the
        direction back from the composition stayed green.
        """
        assert (composition.metric.spec.id, composition.metric.spec.direction) == PRIMARY

    def test_the_secondaries_are_MIXED_direction_in_manifest_order(self, composition):
        """The mixed-direction control, and why order is asserted too.

        A carrier that inherited the primary's direction would render `psnr`
        backwards; one that inherited a single secondary's direction would
        render `mae` backwards. Manifest order is semantic — it is what the
        output stamps — so a reordering is a real change, not cosmetics.
        """
        assert tuple((m.spec.id, m.spec.direction) for m in composition.secondary_metrics) == (
            SECONDARIES
        )

    def test_the_primary_direction_reaches_the_ORDER_AUTHORITY_as_lower(self, composition):
        """A declared string is not yet a semantic; `MetricOrder` is.

        Fails when the direction stops travelling from the declaration to the
        one authority that interprets it — which is exactly the failure the
        tuner cannot see, because it would simply rank candidates the wrong
        way round and report a winner.
        """
        from execute_tools.metric_order import MetricOrder

        order = MetricOrder(composition.metric.spec)
        assert order.is_better(0.01, 0.02)
        assert not order.is_better(0.02, 0.01)
        assert order.direction_words["verb"] == "minimize"

    def test_each_secondary_direction_reaches_the_order_authority_independently(self, composition):
        """Anti-vacuity for the row above: the two must DISAGREE.

        Both secondaries passing one shared direction is precisely the
        collapse this pack exists to falsify, so the assertion is that
        `psnr` prefers the larger value while `mae` prefers the smaller.
        """
        from execute_tools.metric_order import MetricOrder

        by_id = {m.spec.id: MetricOrder(m.spec) for m in composition.secondary_metrics}
        assert by_id["psnr"].is_better(30.0, 20.0)
        assert by_id["mae"].is_better(0.2, 0.3)

    def test_psnr_declares_its_data_range_rather_than_defaulting(self):
        """`data_range = 1.0` is DECLARED, asserted on the declaration FILE.

        Read from the composed object this would be indistinguishable from a
        default the implementation supplied. Read from the JSON, it is the
        task's own statement — and the paired refusal below proves nothing
        would have filled it in.
        """
        declaration = json.loads((DECLARED / "metric_psnr.json").read_text(encoding="utf-8"))
        assert declaration["transform"] == "psnr_db"
        assert declaration["transform_params"] == {"data_range": 1.0}

    def test_psnr_REFUSES_when_the_data_range_is_absent(self, composition):
        """The other half of "declared, not defaulted".

        PSNR is expressed relative to a signal range; guessing 1.0 for a
        deliverable stored in some other scale would report a plausible dB
        figure that is simply wrong. Fails if the implementation ever grows a
        fallback.
        """
        psnr = next(m for m in composition.secondary_metrics if m.spec.id == "psnr")
        stripped = type(psnr)(psnr.spec.model_copy(update={"transform_params": {}}))
        with pytest.raises(ValueError, match="requires a positive `data_range`"):
            # Through `evaluate`, the production entry point: a scoreable
            # deliverable (any real file) so the refusal comes from the metric
            # rather than from the presence contract short-circuiting first.
            stripped.evaluate({0: str(SHIPPED)}, evaluation_payload={}, task_scope=None)

    def test_each_declared_metric_is_bound_to_an_implementation_that_CLAIMS_it(self, composition):
        """D4c's `IMPLEMENTS` check, on the SHIPPED bindings.

        Both secondaries were once bound to `GlobalMseMetric`, which computes
        neither — a terminal report would have carried mean squared error
        under the label `psnr`. Fails if a shipped binding is edited to an
        implementation that claims a different quantity.
        """
        for metric, expected in (
            (composition.metric, "mse"),
            *((m, m.spec.id) for m in composition.secondary_metrics),
        ):
            claimed = type(metric).IMPLEMENTS
            assert claimed, f"{type(metric).__name__} claims nothing, so nothing can be checked"
            assert expected in claimed


# ======================================================================
# 2. The profile: the Q-12-4 contract, and NO TIDMAD-physical field
# ======================================================================


class TestTheDatasetProfile:
    """§A.3b's four fields, and the deletion F-12d-4 demanded."""

    def test_the_profile_carries_the_generic_identity_and_both_declared_file_sets(
        self, composition
    ):
        """`partition_count` + the two REQUIRED file sets, as literals.

        60 is the committed Gate-2 train clip subset the manifest binds — the
        cardinality of the index domain `DataScope` addresses for this run. A
        profile whose count disagreed with its bound manifest would make every
        `range(partition_count)` consumer address clips that do not exist.
        """
        profile = composition.dataset_profile
        assert profile.partition_count == 60
        assert profile.anchor_selection_files == [0]
        assert profile.health_peek_files == [0]

    def test_the_profile_carries_NO_TIDMAD_physical_field_name_by_name(self, composition):
        """Field-by-field, not "looks generic".

        Every name below was present in the fabricated fixture profile before
        D6. Asserting the whole list — rather than the absence of one marker —
        is what makes a partial tidy-up fail.
        """
        flat = json.dumps(composition.dataset_profile.to_wire())
        present = [name for name in FABRICATED if name in flat]
        assert present == []

    def test_the_shipped_declaration_FILE_carries_none_of_them_either(self):
        """The same claim against the bytes on disk.

        The composed object passes through the legacy wire adapter, so a
        source-level assertion is not redundant: a fabricated section could in
        principle be dropped in transit and still sit in the repository.
        """
        raw = (DECLARED / "dataset_profile.json").read_text(encoding="utf-8")
        assert [name for name in FABRICATED if name in raw] == []
        assert "topology" in raw

    def test_the_topology_declares_the_DIFFERING_temporal_extents(self, composition):
        """The §M D6 edge case, asserted as REPRESENTABLE rather than assumed.

        The contract's STOP condition is "temporal rank or differing
        input/target T unrepresentable in the generic identity". It is
        representable: `topology` is opaque and task-owned, so DAVIS states
        both extents and the framework carries them without interpreting
        either. Fails if a future edit collapses the two into one `T`, which
        would make an 8-in/4-out task indistinguishable from an 8-in/8-out
        one.
        """
        spatiotemporal = composition.dataset_profile.topology["spatiotemporal"]
        assert spatiotemporal["temporal_extent_input"] == 8
        assert spatiotemporal["temporal_extent_output"] == 4
        assert spatiotemporal["window_frames"] == 12

    def test_the_typed_forward_declaration_carries_the_same_differing_extents(self):
        """The second, TYPED witness — and the one the framework validates.

        `topology` is opaque by design, so a claim resting only on it would
        rest on a payload nothing checks. `ModelIOContract` is checked, and
        its input and output axes carry 8 and 4 as FIXED dimensions. Fails if
        the pack's declared contract is edited to a shared temporal extent.
        """
        from agent.schemas.model_io_contract import ModelIOContract

        contract = ModelIOContract(
            **json.loads((DECLARED / "model_io_contract.json").read_text(encoding="utf-8"))
        )
        assert [axis.dimension.fixed for axis in contract.input.axes] == [None, 3, 8, 128, 224]
        assert [axis.dimension.fixed for axis in contract.output.axes] == [None, 3, 4, 128, 224]


# ======================================================================
# 3. The task-instance config: `clips_path`, not `sequences_path`
# ======================================================================


class TestTheDeclaredTaskConfiguration:
    """Seam A's `config:` mapping, on the shipped manifest."""

    def test_the_composed_implementation_builds_a_scope_from_the_declared_manifest(
        self, composition
    ):
        """The row COUNT is the evidence.

        60 can only come from `gate2_train.csv`, so it proves the declared
        `config:` actually reached the constructor — the registered
        module-level instance holds no manifest and refuses to build at all.
        """
        from execute_tools.task_data_path import ScopeBuildRequest, resolve_task_scope_capability

        capability = resolve_task_scope_capability(composition.task_data_path)
        scope = capability.build_training_scope(
            ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
        )
        assert type(scope).__name__ == "DavisScope"
        assert len(scope.rows) == 60

    def test_binding_a_SEQUENCES_manifest_instead_is_refused_by_header(self):
        """12bc B8, and the reason `clips_path` is not `sequences_path`.

        `sequences.csv` is a committed, well-formed manifest of the right
        pack — it is simply the wrong LEVEL of identity. The loader refuses it
        by header rather than reading `sequence_name` and inventing clips.
        """
        from execute_tools.davis_data_path import DavisTaskDataPath, ScopeBuildRequest

        implementation = DavisTaskDataPath(clips_path=str(MANIFESTS / "sequences.csv"))
        with pytest.raises(ValueError, match="not a DAVIS clip manifest"):
            implementation.build_training_scope(
                ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
            )

    def test_the_task_description_and_forward_contract_come_from_the_PACK(self, composition):
        """Q-12d-1: task-owned declarations co-locate with the pack.

        Fails if the composed run silently picks up `configs/task_config.yaml`
        — which would hand a DAVIS run TIDMAD's SQUID denoising prose and its
        `[B, T] int64` forward contract, and every prompt would look fine.
        """
        assert "DAVIS" in composition.task_description
        assert "SQUID" not in composition.task_description
        assert composition.forward_contract.input_shape == "[B, 3, 8, 128, 224] float32"
        assert composition.forward_contract.output_shape == "[B, 3, 4, 128, 224] float32"
        assert composition.forward_contract.num_classes == 0


# ======================================================================
# 4. The three lifecycle roles of ONE MAE computation (§22.9a)
# ======================================================================


class TestTheThreeMaeLifecycleRolesStayDistinct:
    """The D6 acceptance criterion that is easiest to satisfy by accident.

    §22.9a freezes DAVIS' MAE as appearing in THREE roles — training objective
    (R1), validation observation (R3), terminal secondary metric (R4-adjacent)
    — and calls them *"three lifecycle roles of one computation"*. The hazard
    is the opposite of the usual one: because the quantity is the same, the
    cheapest implementation is to let one carrier serve all three, at which
    point the run can no longer say whether a number was optimised, observed
    or reported, and the terminal metric silently becomes the training target.
    """

    def test_the_three_roles_are_carried_by_three_DIFFERENT_authorities(self, composition):
        """No object plays two roles.

        Fails the moment a `MetricSpec` starts naming the objective, or the
        loss declaration starts carrying a direction — either collapse would
        make the terminal report a function of what training minimised.
        """
        from execute_tools.evaluation_metric import EvaluationMetric
        from ml_models.models_format_sandbox import LossConfig

        objective = LossConfig(loss_type="custom", loss_name="davis_exact_l1")
        terminal = next(m for m in composition.secondary_metrics if m.spec.id == "mae")

        assert isinstance(terminal, EvaluationMetric)
        assert not isinstance(objective, EvaluationMetric)
        # The objective carries no direction, aggregation or scoreability …
        assert (
            set(LossConfig.model_fields)
            & {
                "direction",
                "aggregation",
                "scoreability",
                "transform",
            }
            == set()
        )
        # … and the terminal metric carries no objective, reduction or beta.
        assert (
            set(type(terminal.spec).model_fields)
            & {
                "loss_type",
                "loss_name",
                "reduction",
                "beta",
            }
            == set()
        )

    def test_the_training_objective_is_NOT_named_by_the_terminal_metric_id(self, composition):
        """`davis_exact_l1` != `mae`, and that gap is load-bearing.

        A loss is resolved BY NAME at training time. If the objective were
        named `mae`, declaring the terminal secondary would be indistinguishable
        from declaring the training target, and removing the secondary would
        change what the model optimises.
        """
        from ml_models.models_format_sandbox import LossConfig

        objective = LossConfig(loss_type="custom", loss_name="davis_exact_l1")
        declared_ids = {composition.metric.spec.id} | {
            m.spec.id for m in composition.secondary_metrics
        }
        assert objective.loss_name not in declared_ids
        assert (PACK / "plugins" / "davis_exact_l1_loss.py").is_file()

    def test_the_validation_observation_is_a_HISTORY_row_not_a_metric(self):
        """R3 lives on `TrainingHistory` and carries no metric identity.

        The pack's own history fixture states `objective_kind == "mae"` and a
        per-epoch `validation_objective`. That string COINCIDES with the
        terminal metric's id — which is the point of §22.9a — so distinctness
        cannot rest on the name. It rests on the carrier: a history row has no
        direction, no aggregation and no scoreability contract, and it never
        enters the run's declared secondary stamp.
        """
        from execute_tools.training_history import TrainingHistory

        payload = json.loads(
            (PACK / "expected" / "training_history_l1_fixture.json").read_text(encoding="utf-8")
        )["training_history"]
        history = TrainingHistory(**payload)
        assert history.objective_kind == "mae"
        assert len(history.validation_objective) == 5
        assert (
            set(TrainingHistory.model_fields)
            & {
                "direction",
                "aggregation",
                "scoreability",
                "spec",
            }
            == set()
        )

    def test_the_terminal_secondary_is_OBSERVATIONAL_beside_a_different_primary(self, composition):
        """The third role, distinguished from the first two by what ranks.

        `mae` is a secondary; the run is ordered by `mse`. If the three roles
        had collapsed, `mae` would be simultaneously the objective, the
        validation number and the ranking quantity — and a composition
        declaring `mae` as the primary would be the SAME run, which the
        duplicate-id refusal below shows it is not.
        """
        assert composition.metric.spec.id == "mse"
        assert "mae" in {m.spec.id for m in composition.secondary_metrics}


# ======================================================================
# 5. The LossConfig constraint — recorded, never widened
# ======================================================================


class TestTheObjectiveConstraintIsRecordedNotWidened:
    """A3's forbidden route, restated where the DAVIS declarations live."""

    def test_smooth_l1_beta_below_the_schema_range_is_REFUSED(self):
        """`beta=0.01` is what exact MAE would need from `smooth_l1`.

        The schema constrains `beta` to [0.1, 10.0]. Widening it to fit one
        task is what D6 forbids: the pack declares its own objective plugin
        instead. Fails if the bound is ever relaxed — at which point DAVIS
        would appear to train on MAE while training on a smoothed surrogate.
        """
        from pydantic import ValidationError

        from ml_models.models_format_sandbox import LossConfig

        with pytest.raises(ValidationError):
            LossConfig(loss_type="smooth_l1", beta=0.01)
        assert LossConfig.model_fields["beta"].metadata

    def test_the_shipped_manifest_declares_the_pack_s_objective_root(self, composition):
        """Without `loss_plugins:` the legal objective is unreachable.

        Loss discovery never saw a pack before D4c, so `davis_exact_l1` could
        be written and not found. Fails if the section is dropped — the run
        would fall back to the global loss library and resolve some other
        implementation of the same name, or none.
        """
        assert composition.loss_plugins == (str(PACK / "plugins"),)


# ======================================================================
# 6. Checksum coverage (F-12d-5)
# ======================================================================


def test_every_committed_manifest_csv_is_checksum_pinned_and_the_digests_match():
    """F-12d-5: the pin covered `sequences.csv` only.

    The Gate reads `clips.csv` and the three `gate2_*.csv`, so corruption or
    an unreviewed regeneration of any of them was undetectable. Coverage is
    asserted as an EXACT set (an added manifest must be pinned or this fails)
    and every digest is recomputed from the bytes.
    """
    from tools.example_packs._common import parse_sha256sums

    pins = parse_sha256sums((MANIFESTS / "SHA256SUMS").read_text(encoding="utf-8"))
    assert set(pins) == {
        "clips.csv",
        "gate2_final.csv",
        "gate2_train.csv",
        "gate2_validation.csv",
        "sequences.csv",
    }
    for name, digest in pins.items():
        assert hashlib.sha256((MANIFESTS / name).read_bytes()).hexdigest() == digest


# ======================================================================
# 7. Negative falsifiers (§M D6 item 6)
# ======================================================================


class TestFalsifiers:
    def test_a_secondary_sharing_the_PRIMARY_id_is_refused(self, variant):
        """The named falsifier.

        `mse` as both the ranked primary and an "observational" secondary
        would reach ordering through one role while claiming exclusion through
        the other. Refused by name at composition, so no run can start in that
        state.
        """
        text = SHIPPED.read_text(encoding="utf-8").replace(
            "  - declaration: ../../examples/davis_future_prediction/declared/metric_psnr.json\n"
            "    implementation:\n"
            "      file: ../../examples/davis_future_prediction/plugins/_davis_metrics.py\n"
            "      symbol: DavisPsnrMetric\n",
            "  - declaration: ../../examples/davis_future_prediction/declared/metric_mse.json\n"
            "    implementation:\n"
            "      module: execute_tools.evaluation_metric\n"
            "      symbol: GlobalMseMetric\n",
        )
        assert "metric_psnr.json" not in text, "the substitution anchor moved"
        with pytest.raises(TaskCompositionError, match="PRIMARY metric"):
            variant(text)

    def test_a_missing_declaration_fails_closed_NAMING_the_family(self, variant):
        """An absent required family must never resolve to TIDMAD's.

        Deleting `dataset_profile:` used to be the quiet path to a DAVIS run
        scored against TIDMAD's topology. The refusal names the section, which
        is what makes it actionable.
        """
        text = SHIPPED.read_text(encoding="utf-8").replace(
            "dataset_profile:\n"
            "  config: ../../examples/davis_future_prediction/declared/dataset_profile.json\n",
            "",
        )
        assert "declared/dataset_profile.json" not in text, "the substitution anchor moved"
        with pytest.raises(TaskCompositionError, match="dataset_profile"):
            variant(text)


# ======================================================================
# 8. Backward compatibility and pack honesty
# ======================================================================


def test_tidmad_composition_fingerprint_is_UNCHANGED():
    """D6 touched no TIDMAD declaration, and this proves it.

    A moved TIDMAD fingerprint would fail every composed TIDMAD workspace's
    resume — the loudest possible consequence of an edit that looked local.
    """
    tidmad = compose_run_task_bindings(str(MANIFEST_DIR / "tidmad.yaml"))
    assert tidmad.semantic_fingerprint == TIDMAD_COMPOSITION_FINGERPRINT


def test_the_shipped_manifest_is_a_POINTER_carrying_no_task_semantics():
    """Q-12d-1: `configs/task_composition/davis.yaml` holds refs, not values.

    Fails if a threshold, a direction or a piece of task prose is inlined into
    the entrypoint — the second copy that then drifts from the pack's own
    declaration with nothing to reconcile them.
    """
    import yaml

    raw = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))
    refs = json.dumps(raw)
    for value in ("lower", "higher", "min_dispersion", "psnr_db", "data_range"):
        assert value not in refs, f"the pointer manifest inlines {value!r}"
    for section in ("dataset_profile", "metric", "task_health", "task_config"):
        assert section in raw


def test_status_claims_L4_only_together_with_its_witness_and_its_non_claims():
    """D-FINAL: promoted, and the promotion must carry what backs it.

    This test used to assert the OPPOSITE — that STATUS said "declarations
    complete, execution pending" — because promotion was D-FINAL's to make
    after ``G-12d`` PASSed. ``G-12d`` PASSed, so the assertion is inverted
    rather than deleted, and the invariant it protects is UNCHANGED: *a
    maturity claim must never outrun its evidence.* Before, that meant
    forbidding the word. Now it means the word alone is not enough.

    Defect caught: someone writes "L4" at the top of a pack and stops there.
    A reader deciding what is safe to rely on then cannot tell which run
    earned it, or — the part that actually misleads — what it still does NOT
    cover. Both packs' composed runs fired ZERO health gates, so a bare "L4"
    would imply a Health demonstration that did not happen.
    """
    status = (PACK / "STATUS.md").read_text(encoding="utf-8")
    heading = next(line for line in status.splitlines() if line.startswith("## Maturity:"))
    assert "L4" in heading and "EXECUTION PENDING" not in heading

    # The witness: which run earned it.
    assert "run_output_g12d_davis_track1.json" in status
    assert "e1c1fa2382405bda7809358deeaed4525ee67be61b34655d708b0d6879aee3ef" in status
    # The non-claims, each named.
    assert "does NOT claim" in status
    assert "health_gate_results` is `[]`" in status
    assert "No scientific claim" in status


# ======================================================================
# F-12d-17 — the train/eval scope separation
# ======================================================================


class TestTheEvalScopeIsNotTheTrainingScope:
    """The runner claim that had no owner in the generic path.

    This pack ships THREE DISJOINT role manifests — train 60, validation 15,
    final 15, with train n validation = 0 — and the ``scope`` column inside
    each one is CONSTANT, so the role IS the file. Before Step 12 / PR-12d
    closed **F-12d-17**, both ``build_training_scope`` and ``build_eval_scope``
    selected from the single ``clips_path``, and a composed run therefore
    trained and evaluated on the identical 60 clips.

    **Nothing green caught it.** Every deterministic scope test constructs a
    scope directly or asserts a round-trip, and ``scripts/run_davis_gate2.py``
    loads all three manifests itself and passes ``task_scope`` and
    ``task_eval_scope`` explicitly (`:201-202`). The composed path is the ONLY
    caller that has to CHOOSE — the same shape as F-12d-7, where the defect
    lived exactly where the harness was doing the production work.

    It matters even though `G-12d` grades neither model quality nor
    convergence: the track would PASS and the shipped manifest would still
    encode a meaningless evaluation. A declaration that ships is one an
    operator will run.
    """

    @staticmethod
    def _keys(scope) -> set[tuple[str, int]]:
        return {(row.sequence_name, row.start_frame) for row in scope.rows}

    @staticmethod
    def _request():
        from execute_tools.task_data_path import ScopeBuildRequest

        return ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)

    def test_the_shipped_composition_evaluates_on_DISJOINT_clips(self):
        """The property, end to end through the shipped manifest."""
        from execute_tools.task_data_path import resolve_task_scope_capability
        from workflows.task_composition import compose_run_task_bindings

        composition = compose_run_task_bindings(str(SHIPPED))
        capability = resolve_task_scope_capability(composition.task_data_path)
        train = self._keys(capability.build_training_scope(self._request()))
        evaluation = self._keys(capability.build_eval_scope(self._request()))

        assert len(train) == 60
        assert len(evaluation) == 15
        assert train & evaluation == set(), (
            "a composed DAVIS run must not evaluate on clips it trained on"
        )

    def test_the_shipped_manifest_DECLARES_the_eval_manifest(self):
        """Reachability: the separation must come from the DECLARATION.

        Without this, the assertion above could pass because of a default,
        and a manifest that forgot the key would silently regress to the
        train==eval pairing.
        """
        import yaml

        raw = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))
        config = raw["task_data_path"]["config"]
        assert config["clips_path"]["ref"].endswith("gate2_train.csv")
        assert config["eval_clips_path"]["ref"].endswith("gate2_validation.csv")

    def test_omitting_the_eval_manifest_FALLS_BACK_rather_than_crashing(self):
        """The fallback is what keeps the fix additive — and it is a hazard.

        Every pre-existing caller (the D14 runner, the module-level
        registration, every current test) constructs with one path and must be
        byte-unchanged. Asserted explicitly so nobody later "tidies" the
        fallback away and breaks them — and so the hazard it preserves is
        visible rather than implied.
        """
        from execute_tools.davis_data_path import DavisTaskDataPath

        single = DavisTaskDataPath(clips_path=str(MANIFESTS / "gate2_train.csv"))
        assert self._keys(single.build_eval_scope(self._request())) == self._keys(
            single.build_training_scope(self._request())
        )

    def test_the_three_role_manifests_really_are_disjoint(self):
        """The premise, not assumed.

        If train and validation overlapped, the assertion above would be
        measuring the manifests rather than the code.
        """
        from execute_tools.davis_data_path import load_davis_clips

        train = {
            (c.sequence_name, c.start_frame)
            for c in load_davis_clips(MANIFESTS / "gate2_train.csv")
        }
        validation = {
            (c.sequence_name, c.start_frame)
            for c in load_davis_clips(MANIFESTS / "gate2_validation.csv")
        }
        assert len(train) == 60
        assert len(validation) == 15
        assert train & validation == set()
