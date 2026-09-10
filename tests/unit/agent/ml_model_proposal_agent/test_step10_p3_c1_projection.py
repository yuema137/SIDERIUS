"""Step 10 / P3 — C1: the typed evidence contract and its ONE projection.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p3_proposer_typed_evidence.md`` §4.1 (the field set), §4.2 (the projection
authority, its placement and its failure policy), §7 C1; parent §11.2.

What this owns, that nothing else can
-------------------------------------
* **The boundary IS the field set.** 30 carried / 12 refused / 2 dead-dropped
  is the claim that this is a consumer view rather than a copy of
  ``InterpretationOutput``. A test that only checked "the carried fields land"
  would stay green while the type drifted into a producer mirror, so the
  refusals are asserted against the LIVE producer schema.
* **Absence is not emptiness.** The pipeline whitelist filters on
  ``is not None``; the CLI feeds legacy artifacts where the distinction is
  real. Only a test that constructs a mapping with keys MISSING can catch a
  projection that coalesces them.
* **Fail-closed, except for the one frozen exception.** A malformed ordinary
  value must raise; a malformed ``metric_identity`` must NOT — it is the P2a
  named absence. Those two behaviours are opposites, and asserting either
  alone would let the other regress.
* **Two entrypoints, one value.** The protocol and the standalone CLI must
  produce EQUAL evidence from identical bytes. This is parent §11.2's
  acceptance rule, and it is checkable only by running both.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_evidence import (
    DEAD_READS,
    NOT_CARRIED,
    ProposerInterpretationEvidence,
    build_proposer_evidence,
)
from tests.unit.agent.ml_model_proposal_agent.test_step10_p3_c0_baselines import (
    full_coverage_interpretation,
    legacy_absence_interpretation,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestTheFieldSetIsABoundary:
    """30 carried, 12 refused, 2 dead-dropped — asserted against live schemas."""

    def test_the_carried_and_refused_fields_partition_the_producer_exactly(self) -> None:
        """No upstream field is silently unaccounted for.

        This is the test that keeps the boundary reviewable: a new
        ``InterpretationOutput`` field must be either carried (because a
        consumer reads it) or listed in ``NOT_CARRIED`` with a reason. Doing
        neither turns this red, which is the review trigger §12 asks for.
        """
        producer = set(InterpretationOutput.model_fields)
        carried = set(ProposerInterpretationEvidence.model_fields)
        refused = set(NOT_CARRIED)

        assert carried <= producer, (
            "the view declares a field the producer does not — a consumer view "
            f"cannot invent evidence: {sorted(carried - producer)}"
        )
        assert carried & refused == set(), (
            f"a field is both carried and refused: {sorted(carried & refused)}"
        )
        unaccounted = producer - carried - refused
        assert unaccounted == set(), (
            "an upstream field is neither carried nor refused-with-a-reason. "
            "Every field addition must answer 'which proposer consumer reads "
            f"it?': {sorted(unaccounted)}"
        )

    def test_the_measured_counts_hold(self) -> None:
        """Hardcoded, because the design froze these exact numbers (§4.1)."""
        assert len(ProposerInterpretationEvidence.model_fields) == 30
        assert len(NOT_CARRIED) == 12
        assert len(InterpretationOutput.model_fields) == 42

    def test_every_refusal_carries_a_reason(self) -> None:
        """A reasonless entry would let the refusal list absorb a real field."""
        for name, reason in NOT_CARRIED.items():
            assert reason.strip(), f"{name} is refused with no stated reason"

    def test_the_dead_reads_are_not_fabricated_into_the_contract(self) -> None:
        """``per_file_comparison`` / ``efficiency_comparison`` never existed.

        The legacy renderer asked for them; the producer never declared them.
        Carrying them would turn a bug into a contract.
        """
        for name in DEAD_READS:
            assert name not in InterpretationOutput.model_fields, (
                f"{name} IS declared upstream — it is not a dead read, and this "
                "module's premise needs re-auditing"
            )
            assert name not in ProposerInterpretationEvidence.model_fields

    def test_raw_secondaries_are_refused_by_name(self) -> None:
        """Q-P3-3 = NO_RAW_SECONDARY_CONSUMPTION, at the schema layer.

        The frozen ruling is that a future exposure needs its own semantic
        ruling and must not arrive incidentally via P5 or another child. A
        field appearing here is exactly how "incidentally" would look.
        """
        assert "per_model_secondary_metrics" not in ProposerInterpretationEvidence.model_fields
        assert "RESERVED" in NOT_CARRIED["per_model_secondary_metrics"]


class TestTheProjectionOnRealDumps:
    """Round-trip over the C0 fixtures — the shapes production actually sees."""

    def test_every_carried_field_lands_from_a_full_dump(self) -> None:
        dump = full_coverage_interpretation()
        evidence = build_proposer_evidence(dump)
        unset = [
            name
            for name in ProposerInterpretationEvidence.model_fields
            if getattr(evidence, name) in (None, {}, [])
        ]
        assert unset == [], (
            "the full-coverage dump populates every upstream field, so a field "
            f"arriving empty means the projection dropped it: {unset}"
        )

    def test_no_refused_field_leaks_onto_the_value(self) -> None:
        evidence = build_proposer_evidence(full_coverage_interpretation())
        for name in NOT_CARRIED:
            assert not hasattr(evidence, name), f"refused field {name} is present on the value"

    def test_the_identity_is_projected_through_the_one_validator(self) -> None:
        evidence = build_proposer_evidence(full_coverage_interpretation())
        assert evidence.metric_identity is not None
        assert evidence.metric_identity.id == "fixture_mse"
        assert evidence.metric_identity.direction == "lower"

    def test_a_legacy_artifact_projects_absences_as_none_not_empty(self) -> None:
        """The distinction the whitelist's ``is not None`` filter renders."""
        evidence = build_proposer_evidence(legacy_absence_interpretation())
        assert evidence.per_model_best is None
        assert evidence.per_model_score_tables is None
        assert evidence.metric_identity is None
        assert evidence.prediction_outcomes_history is None
        # ...while a key that IS present survives, empty or not.
        assert evidence.per_model_best_valid == {
            "step00_alpha_net": 0.0174,
            "step00_beta_net": 0.0172,
        }
        assert evidence.take_home_message == ""
        assert evidence.key_findings == []

    def test_present_but_empty_is_distinguishable_from_absent(self) -> None:
        """Both are legal and they are NOT the same value.

        Asserted directly rather than inferred from prompt bytes, because this
        is the property every absence claim downstream rests on.
        """
        absent = build_proposer_evidence({"model_types": [], "model_descriptions": {}})
        present_empty = build_proposer_evidence(
            {"model_types": [], "model_descriptions": {}, "per_model_best": {}}
        )
        assert absent.per_model_best is None
        assert present_empty.per_model_best == {}

    def test_an_unknown_upstream_key_is_ignored_rather_than_rejected(self) -> None:
        """Forward compatibility: a NEWER producer must not break an older node.

        The view is ``extra="forbid"``, so the projection filters to declared
        names before validating. Without that, adding any field upstream would
        crash every proposer until this module was edited.
        """
        dump = dict(full_coverage_interpretation())
        dump["a_field_from_a_future_step"] = {"anything": 1}
        evidence = build_proposer_evidence(dump)
        assert not hasattr(evidence, "a_field_from_a_future_step")


class TestTheFailurePolicy:
    """Fail-closed everywhere, except the ONE frozen identity exception."""

    def test_a_malformed_ordinary_value_fails_closed(self) -> None:
        dump = dict(full_coverage_interpretation())
        dump["per_model_best"] = "not a mapping"
        with pytest.raises(ValidationError, match="per_model_best"):
            build_proposer_evidence(dump)

    def test_a_malformed_health_history_entry_fails_at_the_projection(self) -> None:
        """The declared behaviour delta: fail-closed EARLIER than before.

        Pre-P3 a malformed history entry reached the renderer and raised there
        (``_format_healthgate_evidence_block``). Typed validation moves the
        failure to the boundary, so the value can no longer be half-valid while
        in flight.
        """
        dump = dict(full_coverage_interpretation())
        dump["collapse_fingerprint_history"] = {"m": [{"not_signature": True}]}
        with pytest.raises(ValidationError, match="collapse_fingerprint_history"):
            build_proposer_evidence(dump)

    @pytest.mark.parametrize(
        "identity",
        [
            {"metric_id": "mse", "direction": "sideways"},
            {"direction": "lower"},
            {"metric_id": "", "direction": "lower"},
            "not a mapping",
            None,
            42,
        ],
    )
    def test_a_malformed_identity_becomes_a_named_absence_not_a_crash(self, identity) -> None:
        """The P2a frozen contract — never a raise, never a default direction."""
        dump = dict(full_coverage_interpretation())
        dump["metric_identity"] = identity
        evidence = build_proposer_evidence(dump)
        assert evidence.metric_identity is None

    def test_the_identity_exception_is_narrow(self) -> None:
        """Anti-vacuity for the test above: a VALID identity still lands.

        Without this, a projection that hardcoded ``metric_identity=None``
        would pass every case in the parametrization.
        """
        dump = dict(full_coverage_interpretation())
        dump["metric_identity"] = {"metric_id": "tidmad_denoising_score", "direction": "higher"}
        evidence = build_proposer_evidence(dump)
        assert evidence.metric_identity is not None
        assert evidence.metric_identity.direction == "higher"

    def test_the_value_is_immutable(self) -> None:
        """Evidence is a fact about a finished run, not a scratchpad."""
        evidence = build_proposer_evidence(full_coverage_interpretation())
        with pytest.raises(ValidationError):
            evidence.take_home_message = "rewritten"  # type: ignore[misc]


class TestBothEntrypointsProduceOneValue:
    """Parent §11.2's acceptance rule, run rather than asserted in prose."""

    def test_protocol_and_cli_agree_on_identical_bytes(self, tmp_path) -> None:
        """The protocol's in-memory dump and the CLI's persisted file.

        The interpreter persists exactly ``model_dump_json``, so these are two
        SOURCES of one shape. Round-tripping through the filesystem — rather
        than reusing the same dict — is what makes the claim about the real CLI
        path instead of about Python object identity.
        """
        from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
            local_full_context,
        )
        from agent.schemas.storage import LocalStorageConfig, StorageConfig

        output = InterpretationOutput.model_validate(full_coverage_interpretation())
        storage = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="p3c1"),
        )
        via_protocol = local_full_context(output, storage).interpretation_evidence

        artifact = tmp_path / "interpretation_p3c1.json"
        artifact.write_text(output.model_dump_json(), encoding="utf-8")
        via_cli = build_proposer_evidence(json.loads(artifact.read_text(encoding="utf-8")))

        assert via_protocol == via_cli
        assert via_protocol is not None
        assert via_protocol.metric_identity == via_cli.metric_identity

    def test_the_equality_would_notice_a_difference(self) -> None:
        """Anti-vacuity: the comparison is not trivially true.

        Frozen Pydantic models compare by value, so two DIFFERENT dumps must
        produce unequal evidence — otherwise the test above would pass even if
        both entrypoints projected nothing.
        """
        assert build_proposer_evidence(full_coverage_interpretation()) != (
            build_proposer_evidence(legacy_absence_interpretation())
        )


class TestTheProjectionHasExactlyOneAuthority:
    """The successor to P2a's ``test_no_typed_evidence_reader_was_introduced``.

    That guard asserted "no reader type exists in ``proposal_helpers.py``" and
    was written expressly to be retired when P3 introduced one. Its PURPOSE —
    the proposer must not grow a second semantic reader — is inherited here in
    a form that survives the type actually existing.
    """

    #: Where the projection legitimately lives. Anything else defining a
    #: same-named function, or a second consumer-view class over the
    #: interpretation, is the second authority parent §11.2 forbids.
    OWNER = "agent/schemas/proposer_evidence.py"

    SEARCH_DIRS = ("agent", "nodes", "workflows", "core", "execute_tools", "scripts")

    def _production_sources(self) -> dict[str, str]:
        """Every production module, as ``relative path -> source``.

        Split out from the scan so a plant can be injected as SOURCE. A census
        whose anti-vacuity proof re-implements the scan inline is not testing
        the census — it is testing ``ast``.
        """
        sources: dict[str, str] = {}
        for directory in self.SEARCH_DIRS:
            for path in (REPO_ROOT / directory).rglob("*.py"):
                rel = path.relative_to(REPO_ROOT).as_posix()
                try:
                    sources[rel] = path.read_text(encoding="utf-8")
                except OSError as exc:  # pragma: no cover - unreadable is a real failure
                    raise AssertionError(f"census could not read {rel}: {exc}") from exc
        return sources

    @staticmethod
    def _definitions_in(sources: dict[str, str], name: str) -> list[str]:
        """Where ``name`` is DEFINED across the given sources.

        A file that does not parse is a hard failure, not a skip: silently
        stepping over it would let a syntax error hide a second authority — the
        census would report "one owner" because it never looked.
        """
        found: list[str] = []
        for rel, source in sorted(sources.items()):
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                raise AssertionError(f"census could not parse {rel}: {exc}") from exc
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                    and node.name == name
                ):
                    found.append(f"{rel}:{node.lineno}")
        return found

    def _definitions_of(self, name: str) -> list[str]:
        return self._definitions_in(self._production_sources(), name)

    def test_build_proposer_evidence_is_defined_exactly_once(self) -> None:
        definitions = self._definitions_of("build_proposer_evidence")
        assert [d.split(":")[0] for d in definitions] == [self.OWNER], (
            "the proposer evidence projection must have ONE owner; a second "
            f"definition is a second semantic reader: {definitions}"
        )

    def test_the_evidence_type_is_defined_exactly_once(self) -> None:
        definitions = self._definitions_of("ProposerInterpretationEvidence")
        assert [d.split(":")[0] for d in definitions] == [self.OWNER], definitions

    @pytest.mark.parametrize(
        ("name", "planted"),
        [
            ("build_proposer_evidence", "def build_proposer_evidence(m):\n    return m\n"),
            (
                "ProposerInterpretationEvidence",
                "class ProposerInterpretationEvidence:\n    pass\n",
            ),
        ],
    )
    def test_the_census_catches_a_planted_second_authority(self, name: str, planted: str) -> None:
        """Anti-vacuity — through the REAL scan, not a re-implementation of it.

        The plant is injected as SOURCE into the actual production source map
        and passed to the same ``_definitions_in`` the census uses, so this
        fails if the scan regresses. An earlier version of this test walked the
        AST itself and asserted ONE hit, which meant it could not fail unless
        ``ast`` broke — it proved nothing about the census. Caught in
        adversarial review.
        """
        sources = self._production_sources()
        baseline = self._definitions_in(sources, name)
        assert [d.split(":")[0] for d in baseline] == [self.OWNER]

        sources["nodes/proposal_helpers.py"] += "\n\n" + planted
        with_plant = self._definitions_in(sources, name)
        owners = [d.split(":")[0] for d in with_plant]
        assert owners == [self.OWNER, "nodes/proposal_helpers.py"], (
            f"the census did not report the planted second definition of {name}: {owners}"
        )

    def test_the_census_refuses_to_skip_a_file_it_cannot_parse(self) -> None:
        """A silent skip is how a census reports 'one owner' having not looked."""
        sources = self._production_sources()
        sources["nodes/proposal_helpers.py"] = "def broken(:\n"
        with pytest.raises(AssertionError, match="could not parse"):
            self._definitions_in(sources, "build_proposer_evidence")


class TestTheVocabEntryRelocation:
    """Verbatim move + re-export: every importer keeps working."""

    def test_the_canonical_home_and_the_re_export_are_one_object(self) -> None:
        from agent.schemas.proposal import VocabEntry as ReExported
        from agent.schemas.vocab import VocabEntry as Canonical

        assert ReExported is Canonical, (
            "the re-export must be an import, not a copy — two classes with the "
            "same name would silently diverge"
        )

    def test_the_upstream_schema_imports_the_canonical_home(self) -> None:
        """The backwards edge §2.7.3 named is gone.

        Asserted on the SOURCE, not on runtime identity: the re-export makes
        both spellings resolve to the same object, so only reading the import
        statement can show which module the edge points at.
        """
        source = (REPO_ROOT / "agent/schemas/interpretation.py").read_text(encoding="utf-8")
        assert "from agent.schemas.vocab import VocabEntry" in source
        assert "from agent.schemas.proposal import VocabEntry" not in source

    def test_every_existing_importer_still_resolves(self) -> None:
        """The measured importer inventory, imported for real.

        Grep-pinned rather than trusted: each module below imports the name
        through ``proposal.py`` today, and the relocation is only safe if all
        of them keep working untouched.
        """
        import importlib

        importers = [
            "nodes.interpretation_helpers",
            "agent.schemas.protocols.ml_result_interp_to_ml_model_propose",
            "agent.prompt_templates.interpretation.rendering",
            "agent.schemas.interpretation",
            "agent.schemas.proposal",
        ]
        for module_name in importers:
            module = importlib.import_module(module_name)
            assert module is not None

    def test_the_relocated_declaration_kept_its_field_names_order_and_defaults(self) -> None:
        """A "verbatim move" that quietly edited a field is not a move.

        Scoped honestly: this pins the field NAMES in order, two defaults and
        one default-factory behaviour. It does NOT compare bytes — a changed
        description or a tightened constraint would pass. Byte-level proof of
        the relocation is the commit diff itself, which shows the class moved
        with no line edited.
        """
        from agent.schemas.vocab import VocabEntry

        assert list(VocabEntry.model_fields) == [
            "name",
            "kind",
            "description",
            "related_to",
            "tier",
            "pattern",
            "proposed_by_run",
            "seen_in_runs",
            "aliases",
            "origin",
        ]
        assert VocabEntry.model_fields["tier"].default == "candidate"
        assert VocabEntry.model_fields["pattern"].default is None
        assert VocabEntry(name="n", kind="feature", description="d").related_to == []


class TestProposalInputCarriesTheEvidence:
    """The schema state after C3 — the typed evidence is the ONLY carrier.

    IR-P3-4 kept the field optional for exactly one commit's worth of
    migration, so the raw-dict fixtures still validated while the readers moved.
    C3 closed that window: the raw dict is gone and this is REQUIRED.
    """

    def test_an_input_cannot_be_built_without_declared_evidence(self) -> None:
        """The requirement, stated behaviourally — the only form that owns it.

        A ``model_fields[...].is_required()`` read-back was dropped here: it
        compares the schema to itself and is the project's own named decoration
        case. The defect worth catching is someone re-adding ``= None``, and
        THIS fails on that. (The census module asserts the same fact once more,
        where it completes the structural claim that no raw carrier survives.)
        """
        with pytest.raises(ValidationError, match="interpretation_evidence"):
            ProposalInput.model_validate(
                {
                    "storage": {
                        "backend": "local",
                        "local": {"workspace": "/tmp/p3c3", "run_name": "x"},
                    }
                }
            )

    def test_a_supplied_evidence_value_survives_validation_unchanged(self) -> None:
        """The protocol hands over a built object; nothing may re-derive it."""
        evidence = build_proposer_evidence(full_coverage_interpretation())
        inp = ProposalInput.model_validate(
            {
                "interpretation_evidence": evidence,
                "storage": {
                    "backend": "local",
                    "local": {"workspace": "/tmp/p3c1", "run_name": "x"},
                },
            }
        )
        assert inp.interpretation_evidence == evidence


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
