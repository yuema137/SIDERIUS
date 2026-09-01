"""Step 12 / PR-12bc — B2: the Q-12-4 DatasetProfile topology contract.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §D.3, §D.3a, §M / B2; audit and
ledger §Q.B2.

```text
DatasetProfile  =  MINIMAL FRAMEWORK-GENERIC IDENTITY
                +  OPAQUE TASK-OWNED TOPOLOGY
```

The generic identity is `partition_count` + the two task-declared file sets;
everything else — PSD geometry, sampling frequency, file-name patterns, h5
channel identities and value encoding — is an opaque payload the framework
never inspects. The membership rule is the operator's, and B2's audit applied
it per consumer (§Q.B2.1) rather than by picking generic-sounding names.

What this module owns
---------------------

* **the LEGACY OBSERVABLE BYTES are pinned** — a TIDMAD run's
  `--dataset_profile_json` payload is byte-identical to the pre-B2 document,
  produced by a bounded projection rather than by keeping duplicate live
  fields (§D.3a);
* **exactly ONE internal semantic authority** — no task-physical field
  survives on the profile as an active generic authority, asserted by a
  census over the model's declared fields;
* **no generic consumer reads task topology** — a census over a NAMED list of
  generic-core modules, with a planted read proving it turns RED;
* **a profile with no PSD/segment/pattern values works** — it constructs,
  validates, and every generic-identity reader consumes it;
* **the legacy adapters are bounded and correct** — the wire reader, the wire
  writer and `model_copy` all understand the pre-B2 section names, share ONE
  definition of that shape, and none of them aliases the profile's own state.

What is deliberately NOT here: assertions that Pydantic rejects a bad
`Literal`, that a required field is required, or that a default is its
default. CLAUDE.md forbids pytesting what a declaration already enforces.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from execute_tools.dataset_config import (
    NUM_FILES,
    TIDMAD,
    TIDMAD_PROFILE,
    ChannelIdentity,
    DataScope,
    DatasetConfig,
    DatasetProfile,
    ValueEncoding,
    tidmad_topology,
)
from execute_tools.sample_set_builder import build_sample_set

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


# ======================================================================
# 1. The legacy observable bytes
# ======================================================================


class TestTheLegacyWireBytesArePinned:
    """§D.3a: byte compatibility lives at the transport/persistence boundary."""

    def test_the_wire_form_reproduces_the_pre_b2_document_exactly(self):
        """Hardcoded, never read back from the model under test.

        This is the exact document `--dataset_profile_json` carried before
        B2 — `DatasetProfile.model_dump()` when `dataset` / `channels` /
        `encoding` were fields. Key ORDER is asserted too, via `json.dumps`,
        because the bytes are what crosses.
        """
        expected = {
            "dataset": {
                "psd_segment_length": 10_000_000,
                "segments_per_file": 200,
                "num_files": 20,
                "sampling_frequency": 10_000_000.0,
                "training_file_pattern": "abra_training_{file_index:04d}.h5",
                "validation_file_pattern": "abra_validation_{file_index:04d}.h5",
            },
            "channels": {"input_channel": "channel0001", "target_channel": "channel0002"},
            "encoding": {
                "storage_dtype": "int8",
                "compute_dtype": "int16",
                "value_offset": 128,
                "num_classes": 256,
            },
            "anchor_selection_files": [0, 10, 19],
            "health_peek_files": [3, 10, 17],
        }
        assert json.dumps(TIDMAD_PROFILE.to_wire()) == json.dumps(expected)

    def test_the_step00_golden_still_describes_what_crosses(self):
        """The Step-00 golden pins `TIDMAD.model_dump()` field by field, and
        `DatasetProfile`'s docstring said it composes rather than replaces in
        order to preserve exactly that. After B2 the composition is by
        PAYLOAD instead of by field, so this states the surviving link.
        """
        assert TIDMAD_PROFILE.to_wire()["dataset"] == TIDMAD.model_dump()

    def test_a_legacy_document_round_trips_to_an_equal_profile(self):
        assert DatasetProfile.model_validate(TIDMAD_PROFILE.to_wire()) == TIDMAD_PROFILE

    def test_the_parent_writes_the_wire_form_not_the_internal_model(self):
        """The transport site itself. `model_dump()` would now emit
        `partition_count` + `topology` and change every child's config file.
        """
        src = (REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8")
        assert "resolve_dataset_profile().to_wire()" in src
        assert "resolve_dataset_profile().model_dump()" not in src

    def test_the_composition_fingerprint_payload_uses_the_wire_form(self):
        """The composition fingerprint must not move at B2. A composed
        workspace's resume compares it, so serializing the new internal shape
        into the payload would fail every existing composed resume for a
        reason that has nothing to do with the task's semantics.
        """
        src = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        assert '"dataset_profile": dataset_profile.to_wire(),' in src


# ======================================================================
# 2. ONE internal semantic authority
# ======================================================================


class TestExactlyOneSemanticAuthority:
    """§D.3a: no task-physical field survives as a live generic authority."""

    def test_the_declared_field_set_is_the_audited_one(self):
        assert set(DatasetProfile.model_fields) == {
            "partition_count",
            "topology",
            "anchor_selection_files",
            "health_peek_files",
        }

    @pytest.mark.parametrize(
        "retired", ["dataset", "channels", "encoding", "num_files", "psd_segment_length"]
    )
    def test_no_task_physical_field_survives_on_the_profile(self, retired):
        """The census the acceptance criterion asks for, over the RESOLVED
        profile's fields. A compatibility field re-added "just for now" is
        the second live authority §D.3a exists to prevent.
        """
        assert retired not in DatasetProfile.model_fields

    def test_the_partition_count_is_the_only_topology_fact_the_schema_names(self):
        """`topology` is typed as an opaque mapping, so the framework's TYPE
        system knows nothing about any task's physical layout — which is what
        makes "no built-in topology catalog" structural rather than a promise.
        """
        annotation = str(DatasetProfile.model_fields["topology"].annotation)
        assert "DatasetConfig" not in annotation
        assert "ChannelIdentity" not in annotation
        assert "ValueEncoding" not in annotation


# ======================================================================
# 3. No generic consumer reads task topology
# ======================================================================

#: Modules that are FRAMEWORK-GENERIC by the B2 audit: they reason about the
#: partition domain and nothing else about the dataset. Named explicitly —
#: a census over "everything" would be unmaintainable, and a census that
#: silently skipped a module would be the F-P2b-4 failure mode.
GENERIC_CORE_MODULES = (
    "core/resume.py",
    "core/campaign_artifacts.py",
    "execute_tools/health_checks/config.py",
    "execute_tools/health_checks/pearson_dispersion.py",
    "execute_tools/health_checks/per_file_output_std.py",
    "nodes/ml_hyperparameter_tune_agent/records.py",
    "nodes/scoring_reference.py",
    "agent/schemas/score_table.py",
    "execute_tools/scoring_helpers.py",
)

#: The one function that decodes the opaque payload. A generic module calling
#: it is a generic module reading task topology.
TOPOLOGY_READERS = ("tidmad_topology", "resolve_tidmad_topology")


def _calls(rel: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            out.add(node.func.id)
        if isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


class TestNoGenericConsumerReadsTaskTopology:
    @pytest.mark.parametrize("rel", GENERIC_CORE_MODULES)
    def test_a_generic_module_never_decodes_the_opaque_payload(self, rel):
        offenders = sorted(_calls(rel) & set(TOPOLOGY_READERS))
        assert offenders == [], (
            f"{rel} calls {offenders} — a GENERIC consumer is reading TASK "
            f"topology. Either the fact it needs belongs in generic identity "
            f"(prove it with a cross-task consumer audit, §Q.B2.1) or the "
            f"consumer belongs behind the task's own code."
        )

    @pytest.mark.parametrize("rel", GENERIC_CORE_MODULES)
    def test_a_generic_module_never_names_a_topology_field(self, rel):
        """The second direction. A module could read the payload by
        subscript (``profile.topology["dataset"]``) without calling the view,
        which the call census alone would not see.
        """
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert ".topology[" not in src, (
            f"{rel} subscripts the opaque topology payload directly. The "
            f"framework never inspects inside it."
        )

    def test_the_census_is_not_vacuous(self):
        """The plant, proven rather than asserted: a module that DOES decode
        the payload is detected by the same census. Without this the two
        tests above would pass on an empty intersection forever — the
        anchored-symbol lesson (F-P2b-4)."""
        known_reader = "execute_tools/train_engine_sandbox.py"
        assert _calls(known_reader) & set(TOPOLOGY_READERS), (
            "the census cannot see a topology read at all — it would report "
            "every generic module clean for the wrong reason"
        )


# ======================================================================
# 4. A profile with NO task topology
# ======================================================================

#: The acceptance criterion made concrete: a task with no PSD segments, no
#: sampling frequency, no file-name pattern and no h5 channels.
TOPOLOGY_FREE = DatasetProfile(
    partition_count=4,
    anchor_selection_files=[0, 2],
    health_peek_files=[1],
)


class TestATaskWithNoPhysicalTopology:
    def test_it_constructs_and_validates(self):
        assert TOPOLOGY_FREE.partition_count == 4
        assert TOPOLOGY_FREE.topology == {}

    def test_every_generic_identity_reader_consumes_it(self):
        """The generic readers, exercised — not merely asserted to exist."""
        assert DataScope.default().resolve(TOPOLOGY_FREE.partition_count) == [0, 1, 2, 3]
        assert DataScope.default().is_full(TOPOLOGY_FREE.partition_count)
        assert DataScope(file_indices=[1, 2]).resolve(TOPOLOGY_FREE.partition_count) == [1, 2]
        assert not DataScope(file_indices=[1]).is_full(TOPOLOGY_FREE.partition_count)

    def test_its_declared_file_sets_are_validated_against_its_own_count(self):
        """Fail-closed against THIS task's partition domain, not TIDMAD's."""
        with pytest.raises(ValueError, match="does not have"):
            DatasetProfile(
                partition_count=4,
                anchor_selection_files=[0, 19],
                health_peek_files=[1],
            )

    def test_it_round_trips_through_the_wire_without_inventing_topology(self):
        """No TIDMAD-shaped default is fabricated on the way out — the
        failure the Pets fixture demonstrates (§Q.B2.0).
        """
        wire = TOPOLOGY_FREE.to_wire()
        assert "dataset" not in wire
        assert "channels" not in wire
        assert wire["partition_count"] == 4
        assert DatasetProfile.model_validate(wire) == TOPOLOGY_FREE

    def test_tidmad_physical_code_refuses_it_BY_NAME(self):
        """The whole point of the split: a task that declared no TIDMAD
        layout gets a named refusal, never a fabricated sampling frequency.
        """
        with pytest.raises(ValueError, match="declares no TIDMAD topology"):
            tidmad_topology(TOPOLOGY_FREE)


# ======================================================================
# 5. The bounded legacy adapters
# ======================================================================


class TestTheLegacyAdaptersAreBoundedAndCorrect:
    def test_one_definition_of_the_legacy_shape(self):
        """The wire reader, the wire writer and `model_copy` must not drift.
        Three call sites, one tuple.
        """
        assert DatasetProfile._LEGACY_SECTIONS == ("dataset", "channels", "encoding")

    def test_direct_keyword_construction_still_works(self):
        """The pre-B2 spelling. Rejecting it would turn every legacy caller
        into an obscure "partition_count field required".
        """
        p = DatasetProfile(
            dataset=DatasetConfig(
                psd_segment_length=100,
                segments_per_file=5,
                num_files=2,
                sampling_frequency=1.0,
                training_file_pattern="t_{file_index}.h5",
                validation_file_pattern="v_{file_index}.h5",
            ),
            channels=ChannelIdentity(input_channel="a", target_channel="b"),
            encoding=ValueEncoding(
                storage_dtype="int8", compute_dtype="int16", value_offset=128, num_classes=256
            ),
            anchor_selection_files=[0],
            health_peek_files=[1],
        )
        assert p.partition_count == 2
        assert tidmad_topology(p).dataset.segments_per_file == 5

    def test_model_copy_carries_partition_count_along_with_num_files(self):
        """A CORRECTNESS fix, not a convenience. `model_copy(update=...)`
        bypasses validation, so after the split
        `model_copy(update={"dataset": smaller})` would have silently done
        NOTHING and returned a profile still claiming 20 partitions.
        """
        smaller = TIDMAD_PROFILE.model_copy(
            update={
                "dataset": tidmad_topology(TIDMAD_PROFILE).dataset.model_copy(
                    update={"num_files": 7}
                )
            }
        )
        assert smaller.partition_count == 7
        assert tidmad_topology(smaller).dataset.num_files == 7

    def test_the_wire_form_is_not_aliased_to_the_profiles_own_state(self):
        """`DatasetProfile` is frozen; a plain dict inside it is not.

        Returning the profile's own sections let
        `TIDMAD_PROFILE.to_wire()["dataset"].update(...)` — the obvious way
        to build a variant — mutate the SHIPPED profile for the rest of the
        process. That is not hypothetical: it is what this method did when
        first written, and it silently poisoned every later test in the same
        interpreter.
        """
        wire = TIDMAD_PROFILE.to_wire()
        wire["dataset"]["num_files"] = 999
        wire["anchor_selection_files"].append(99)
        assert TIDMAD_PROFILE.partition_count == NUM_FILES
        assert TIDMAD_PROFILE.topology["dataset"]["num_files"] == NUM_FILES
        assert TIDMAD_PROFILE.anchor_selection_files == [0, 10, 19]

    def test_a_constructed_profile_does_not_alias_the_callers_dict(self):
        """The same rule in the other direction."""
        payload = TIDMAD_PROFILE.to_wire()
        built = DatasetProfile.model_validate(payload)
        payload["dataset"]["segments_per_file"] = 1
        assert tidmad_topology(built).dataset.segments_per_file == 200


# ======================================================================
# 6. Legacy behaviour is unchanged
# ======================================================================


class TestLegacyBehaviourIsIdentical:
    def test_the_shipped_profile_still_selects_exactly_what_it_did(self):
        """The generic identity and the task topology are read from ONE
        profile, so a selection cannot straddle two topologies.
        """
        got = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.01,
            seed=7,
            profile=TIDMAD_PROFILE,
        )
        assert sorted(got) == list(range(NUM_FILES))
        assert all(len(v) == 2 for v in got.values())

    def test_the_anchor_strategy_still_reads_the_tasks_own_declaration(self):
        got = build_sample_set(
            is_trial=True,
            trial_strategy="anchors",
            trial_portion=0.01,
            seed=7,
            profile=TIDMAD_PROFILE,
        )
        assert sorted(got) == TIDMAD_PROFILE.anchor_selection_files

    def test_scope_resolution_is_unchanged_for_the_shipped_topology(self):
        assert DataScope.default().resolve(TIDMAD_PROFILE.partition_count) == list(range(20))
        assert DataScope.from_cli("4-9").resolve(TIDMAD_PROFILE.partition_count) == [
            4,
            5,
            6,
            7,
            8,
            9,
        ]
