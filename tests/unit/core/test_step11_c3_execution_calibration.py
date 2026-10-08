"""Address-space declaration, explicit historical settings and resume provenance.

The current default inherits OS limits. Historical host values remain executable
only as explicit caller configuration; no scientific run is inferred from them.
"""

from __future__ import annotations

import json

import pytest

from core.execution_calibration import (
    ROLE_CEILINGS,
    ROLE_DEFAULT_RSS_GB,
    RSS_OVERRIDE_ENV_VAR,
    MalformedCeilingOverride,
    calibration_provenance,
    resolve_role_ceiling,
    resolve_role_ceiling_gb,
)
from core.run_invariants import (
    RunInvariants,
    ensure_run_invariants,
    load_run_invariants,
    write_run_invariants,
)


def _invariants(**overrides) -> RunInvariants:
    base = {
        "resolved_data_scope": [0, 1],
        "health_gate_enabled": True,
        "health_config_sha256": "a" * 64,
        "runtime_estimator_identity": "est-1",
        "runtime_policy_identity": "pol-1",
    }
    base.update(overrides)
    return RunInvariants(**base)


# ----------------------------------------------------------------------
# R-11-5 — the ladder
# ----------------------------------------------------------------------


class TestTheResolutionLadder:
    def test_all_three_defaults_declare_inheritance(self):
        assert ROLE_DEFAULT_RSS_GB == {"training": None, "inference": None, "scoring": None}
        assert set(ROLE_CEILINGS) == {"training", "inference", "scoring"}

    def test_no_override_resolves_the_declared_default(self, monkeypatch):
        monkeypatch.delenv(RSS_OVERRIDE_ENV_VAR, raising=False)
        for role, ceiling in ROLE_CEILINGS.items():
            assert resolve_role_ceiling_gb(role) == ceiling.gib

    def test_the_override_wins_for_every_role(self, monkeypatch):
        monkeypatch.setenv(RSS_OVERRIDE_ENV_VAR, "11")
        for role in ROLE_CEILINGS:
            assert resolve_role_ceiling_gb(role) == 11

    def test_zero_still_disables(self, monkeypatch):
        monkeypatch.setenv(RSS_OVERRIDE_ENV_VAR, "0")
        assert resolve_role_ceiling_gb("training") == 0

    def test_one_override_can_calibrate_roles_independently(self, monkeypatch):
        """An H100 training VA escape must not silently disable scoring bounds."""
        monkeypatch.setenv(
            RSS_OVERRIDE_ENV_VAR,
            "training=0,inference=96,scoring=24",
        )
        assert resolve_role_ceiling_gb("training") == 0
        assert resolve_role_ceiling_gb("inference") == 96
        assert resolve_role_ceiling_gb("scoring") == 24

    def test_there_is_no_third_layer(self, monkeypatch):
        """§9.3 finding 14. The resolved value must be a function of the
        override and the role ALONE — no per-task, per-run or per-host
        third source may creep in.

        Asserted behaviourally: with the override unset, every role
        inherits the OS and nothing else can move it.
        """
        monkeypatch.delenv(RSS_OVERRIDE_ENV_VAR, raising=False)
        monkeypatch.setenv("SIDERIUS_TASK", "pets")
        monkeypatch.setenv("SIDERIUS_DATA_DIR", "/somewhere/else")
        assert resolve_role_ceiling_gb("inference") is None

    def test_an_explicit_environment_can_be_supplied(self, monkeypatch):
        """The resolver takes the mapping as a parameter so a caller can
        resolve against a TRANSPORTED environment rather than the ambient
        one — the same discipline C1 applied to the spawner.
        """
        monkeypatch.setenv(RSS_OVERRIDE_ENV_VAR, "99")
        assert resolve_role_ceiling_gb("training", environ={}) is None

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="unknown role"):
            resolve_role_ceiling_gb("compilation")


class TestMalformedOverridesRefuse:
    @pytest.mark.parametrize("bad", ["4O", "not-a-number", "12.5", "", " ", "40GiB"])
    def test_unparseable_refuses(self, monkeypatch, bad):
        monkeypatch.setenv(RSS_OVERRIDE_ENV_VAR, bad)
        with pytest.raises(MalformedCeilingOverride):
            resolve_role_ceiling_gb("training")

    def test_negative_refuses(self, monkeypatch):
        monkeypatch.setenv(RSS_OVERRIDE_ENV_VAR, "-1")
        with pytest.raises(MalformedCeilingOverride, match="negative"):
            resolve_role_ceiling_gb("training")

    @pytest.mark.parametrize(
        "bad",
        [
            "training=0,inference=96",
            "training=0,inference=96,scoring=24,unknown=1",
            "training=0,inference=96,scoring=",
            "training=0,inference=96,training=24,scoring=24",
        ],
    )
    def test_malformed_role_mapping_refuses(self, monkeypatch, bad):
        monkeypatch.setenv(RSS_OVERRIDE_ENV_VAR, bad)
        with pytest.raises(MalformedCeilingOverride):
            resolve_role_ceiling_gb("training")

    def test_the_refusal_is_actionable(self, monkeypatch):
        monkeypatch.setenv(RSS_OVERRIDE_ENV_VAR, "4O")
        with pytest.raises(MalformedCeilingOverride) as exc:
            resolve_role_ceiling_gb("training")
        message = str(exc.value)
        assert RSS_OVERRIDE_ENV_VAR in message
        assert "4O" in message
        assert "0" in message, "the disable escape hatch must be reachable from the error"


# ----------------------------------------------------------------------
# Provenance / F-11-3
# ----------------------------------------------------------------------


class TestDeclaredProvenance:
    def test_every_role_distinguishes_absence_and_explicit_zero(self):
        for role in ("training", "inference", "scoring"):
            inherited = resolve_role_ceiling(role, environ={})
            zero = resolve_role_ceiling(role, environ={RSS_OVERRIDE_ENV_VAR: "0"})
            assert inherited.gib is None and inherited.source == "inherited_os"
            assert zero.gib == 0 and zero.source == "environment"

    def test_historical_inference_cap_requires_explicit_configuration(self):
        # The old 60-GiB inference value is retained as a caller declaration,
        # not an assumption about every host or an assertion about paper runs.
        environment = {RSS_OVERRIDE_ENV_VAR: "training=40,inference=60,scoring=24"}
        assert resolve_role_ceiling_gb("inference", environ=environment) == 60
        assert resolve_role_ceiling_gb("inference", environ={}) is None

    def test_incident_scoring_cap_remains_explicitly_selectable(self):
        environment = {RSS_OVERRIDE_ENV_VAR: "training=40,inference=60,scoring=24"}
        assert resolve_role_ceiling_gb("scoring", environ=environment) == 24
        assert resolve_role_ceiling("scoring", environ=environment).source == "environment"

    def test_the_stale_arithmetic_is_gone_from_the_launch_path(self):
        """R-11-11: `sandbox_executor.py` is a CONSUMER. The prose sum that
        went stale unnoticed must not still be sitting there beside the
        corrected declaration.
        """
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parents[3] / "src/core" / "sandbox_executor.py"
        ).read_text(encoding="utf-8")
        assert "inference_single.py:325-331" not in src
        assert "core/execution_calibration.py" in src

    def test_the_provenance_payload_is_json_native(self):
        """An auditor reading a lock file must need no code to interpret
        it.
        """
        payload = calibration_provenance(environ={})
        assert json.loads(json.dumps(payload)) == payload
        assert set(payload["roles"]) == set(ROLE_CEILINGS)
        assert payload["roles"]["inference"]["gib"] is None
        assert payload["roles"]["inference"]["source"] == "inherited_os"
        assert payload["limit_kind"] == "RLIMIT_AS" and payload["unit"] == "GiB"
        assert payload["override_env"] is None

    def test_the_payload_records_the_override_that_was_in_force(self):
        payload = calibration_provenance(environ={RSS_OVERRIDE_ENV_VAR: "8"})
        assert payload["override_env"] == "8"
        assert payload["roles"]["training"]["gib"] == 8
        assert payload["roles"]["training"]["source"] == "environment"

    def test_the_payload_records_role_specific_effective_values(self):
        raw = "training=0,inference=96,scoring=24"
        payload = calibration_provenance(environ={RSS_OVERRIDE_ENV_VAR: raw})
        assert payload["override_env"] == raw
        assert {role: item["gib"] for role, item in payload["roles"].items()} == {
            "training": 0,
            "inference": 96,
            "scoring": 24,
        }


# ----------------------------------------------------------------------
# R-11-6 — recorded, not enforced, and structurally distinguishable
# ----------------------------------------------------------------------


class TestTheLockRecordsButDoesNotEnforce:
    def test_canonical_and_provenance_partition_every_field(self):
        """The operator's added R-11-6 constraint, made executable.

        "Absent from `_CANONICAL`" is a validator remembering not to
        compare something. This asserts the stronger property: every
        declared field is classified as EITHER a semantic invariant OR
        execution provenance, so a future field cannot be silently
        unclassified — which is exactly how a generic validator would
        comparison-sweep the ceilings by accident.
        """
        canonical = set(RunInvariants._CANONICAL)
        provenance = set(RunInvariants._PROVENANCE)
        declared = set(RunInvariants.model_fields)
        assert canonical & provenance == set(), "a field cannot be both"
        assert canonical | provenance == declared, (
            "every field must be classified; unclassified: "
            f"{sorted(declared - canonical - provenance)}"
        )

    def test_the_ceilings_are_provenance_not_canonical(self):
        assert "execution_calibration" in RunInvariants._PROVENANCE
        assert "execution_calibration" not in RunInvariants._CANONICAL

    def test_a_resume_under_different_host_calibration_stays_legal(self, tmp_path):
        """The scientific consequence, end-to-end against the real lock.

        Same run, differently-calibrated host. Unlike a composition, metric
        or dataset-semantics change, this must NOT be refused: the ceilings
        describe the machine, not the experiment.
        """
        workspace = str(tmp_path / "ws")
        first = _invariants(execution_calibration=calibration_provenance(environ={}))
        write_run_invariants(workspace, first)

        resumed = _invariants(
            execution_calibration=calibration_provenance(environ={RSS_OVERRIDE_ENV_VAR: "8"})
        )
        assert ensure_run_invariants(workspace, resumed) == "validated"

    def test_a_semantic_change_is_still_refused(self, tmp_path):
        """The counterfactual. Without it the test above would pass on a
        lock that had stopped comparing anything at all.
        """
        from core.run_invariants import RunInvariantsViolation

        workspace = str(tmp_path / "ws")
        write_run_invariants(workspace, _invariants(execution_calibration=calibration_provenance()))
        with pytest.raises(RunInvariantsViolation):
            ensure_run_invariants(workspace, _invariants(resolved_data_scope=[0, 1, 2]))

    def test_a_pre_c3_lock_file_stays_byte_identical(self, tmp_path):
        """A lock written before calibration was recorded must not gain a
        `null` for a concept it predates — the same rule Step 10 / P1 set
        for the composition fingerprint.
        """
        workspace = tmp_path / "ws"
        path = write_run_invariants(str(workspace), _invariants(created_at="2026-01-01T00:00:00"))
        payload = json.loads(open(path, encoding="utf-8").read())
        assert "execution_calibration" not in payload

    def test_a_pre_c3_lock_file_still_loads(self, tmp_path):
        workspace = tmp_path / "ws"
        write_run_invariants(str(workspace), _invariants(created_at="2026-01-01T00:00:00"))
        loaded = load_run_invariants(str(workspace))
        assert loaded is not None
        assert loaded.execution_calibration is None

    def test_the_calibration_reaches_a_real_lock_file(self, tmp_path):
        """Reachability: the field existing on the model proves nothing if
        no writer populates it.
        """
        workspace = tmp_path / "ws"
        path = write_run_invariants(
            str(workspace), _invariants(execution_calibration=calibration_provenance(environ={}))
        )
        payload = json.loads(open(path, encoding="utf-8").read())
        assert payload["execution_calibration"]["roles"]["training"]["gib"] is None
        assert payload["execution_calibration"]["roles"]["inference"]["source"] == "inherited_os"


class TestTheSharedBuilderStampsIt:
    def test_build_run_invariants_populates_the_calibration(self, tmp_path, monkeypatch):
        """C9d's lesson applied: stamped at the ONE shared builder, so every
        entry point records what its children ran under.
        """
        from core.run_invariants import build_run_invariants

        monkeypatch.delenv(RSS_OVERRIDE_ENV_VAR, raising=False)

        invariants, _ = build_run_invariants(
            resolved_data_scope=[0, 1],
            health_gate_enabled=False,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path / "ws"),
            task_composition_fingerprint="synthetic-composition-for-calibration-test",
        )
        assert invariants.execution_calibration is not None
        assert invariants.execution_calibration["roles"]["scoring"]["gib"] is None
        assert invariants.execution_calibration["roles"]["scoring"]["source"] == "inherited_os"


def test_selected_role_parser_semantics_are_unchanged():
    environment = {RSS_OVERRIDE_ENV_VAR: "training=7,inference=-1,scoring=24"}
    assert resolve_role_ceiling_gb("training", environ=environment) == 7
    with pytest.raises(MalformedCeilingOverride, match="negative"):
        resolve_role_ceiling_gb("inference", environ=environment)
    with pytest.raises(MalformedCeilingOverride, match="negative"):
        calibration_provenance(environ=environment)


def test_historical_calibration_record_remains_readable_and_unmodified(tmp_path):
    from pathlib import Path

    historical = {
        "override_env": None,
        "roles": {
            "training": {
                "gib": 40,
                "declared_gib": 40,
                "derivation": "measured",
                "set_on": "2026-04-20",
            },
            "inference": {
                "gib": 60,
                "declared_gib": 60,
                "derivation": "empirical_unverified",
                "set_on": "2026-07-13",
            },
            "scoring": {
                "gib": 24,
                "declared_gib": 24,
                "derivation": "incident",
                "set_on": "2026-04-20",
            },
        },
    }
    workspace = str(tmp_path / "old-run")
    path = Path(write_run_invariants(workspace, _invariants(execution_calibration=historical)))
    original = path.read_bytes()
    loaded = load_run_invariants(workspace)
    assert loaded is not None and loaded.execution_calibration == historical
    assert (
        ensure_run_invariants(
            workspace, _invariants(execution_calibration=calibration_provenance(environ={}))
        )
        == "validated"
    )
    assert path.read_bytes() == original
