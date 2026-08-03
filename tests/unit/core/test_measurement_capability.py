"""A measurement path that can say why it is off.

V20 PR C1 / C-C3a, design §15.3.

`probe_runner_availability()` refused unless `TIDMAD_DATA_DIR` was a
readable directory, and the tuner consults it before any bounded live probe.
On any other task the entire measured-evidence path disabled itself and the
run continued on static priors -- the V19 posture the V20 launch gate exists
to end.

The failure mode worth naming: that is a task assumption expressed by
OMISSION inside generic infrastructure. There is no wrong constant to grep
for. It fails by returning False, which reads like a legitimate environment
answer.

So the replacement is generic, and it cannot be silent: an unavailable
capability without a reason is refused by a validator, not by convention.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.runtime_control.measurement_capability import (
    ResolvedMeasurementCapability,
    resolve_measurement_capability,
)

IDENTITY = {
    "task_identity": "tidmad_denoise",
    "dataset_adapter": "tidmad_hdf5",
    "data_shape_class": "seg40000_int8",
}


class TestUnavailabilityMustExplainItself:
    def test_a_reasonless_refusal_is_rejected(self):
        """The whole point. `probe_available=False` with no reason is the
        shape the old `(bool, str)` tuple allowed by convention and this
        model forbids by construction."""
        with pytest.raises(ValidationError, match="unavailability_reason"):
            ResolvedMeasurementCapability(**IDENTITY, probe_available=False)

    def test_a_blank_reason_is_rejected(self):
        with pytest.raises(ValidationError):
            ResolvedMeasurementCapability(
                **IDENTITY, probe_available=False, unavailability_reason="   "
            )

    def test_available_and_refused_cannot_both_be_true(self):
        with pytest.raises(ValidationError):
            ResolvedMeasurementCapability(
                **IDENTITY, probe_available=True, unavailability_reason="but also no"
            )

    def test_the_reason_survives_into_the_operator_line(self):
        cap = ResolvedMeasurementCapability(
            **IDENTITY,
            probe_available=False,
            unavailability_reason="no dataset root was supplied by the caller",
        )
        assert "not measurable" in cap.detail
        assert "no dataset root" in cap.detail


class TestIdentityTravelsWithTheVerdict:
    """A capability that says "yes" without saying what it would be
    measuring cannot supply a `MeasurementIdentity` later, and the identity
    is what PR C exists to establish."""

    @pytest.mark.parametrize("field", sorted(IDENTITY))
    def test_identity_is_required_even_when_unavailable(self, field):
        """ "We cannot measure task X" is a more useful fact than "we cannot
        measure"."""
        partial = {k: v for k, v in IDENTITY.items() if k != field}
        with pytest.raises(ValidationError):
            ResolvedMeasurementCapability(
                **partial, probe_available=False, unavailability_reason="r"
            )

    @pytest.mark.parametrize("field", sorted(IDENTITY))
    def test_no_identity_field_may_be_blank(self, field):
        with pytest.raises(ValidationError):
            ResolvedMeasurementCapability(
                **{**IDENTITY, field: ""},
                probe_available=False,
                unavailability_reason="r",
            )

    def test_an_unrecognised_field_is_refused(self):
        with pytest.raises(ValidationError):
            ResolvedMeasurementCapability(
                **IDENTITY,
                probe_available=False,
                unavailability_reason="r",
                tidmad_data_dir="/some/path",
            )


class TestTheResolverIsGeneric:
    def test_a_missing_dataset_root_is_refused_not_defaulted(self):
        """The defect, inverted. The old code reached for `TIDMAD_DATA_DIR`
        when it needed a dataset; this refuses and says so, because a
        default here would be exactly the task assumption being removed."""
        cap = resolve_measurement_capability(
            **IDENTITY, dataset_root=None, supported_phases=("training",)
        )
        assert cap.probe_available is False
        assert "no dataset root" in (cap.unavailability_reason or "")

    def test_a_nonexistent_root_names_the_path(self, tmp_path):
        cap = resolve_measurement_capability(**IDENTITY, dataset_root=str(tmp_path / "absent"))
        assert cap.probe_available is False
        assert "absent" in (cap.unavailability_reason or "")

    def test_the_resolver_never_raises(self, tmp_path):
        """Same contract the `(bool, str)` version had: the CALLER decides
        whether unavailability is fatal. A real formal launch treats it as
        fatal; a CPU or pseudo run expects it."""
        for root in (None, "", str(tmp_path), "/definitely/not/here"):
            cap = resolve_measurement_capability(**IDENTITY, dataset_root=root)
            assert isinstance(cap, ResolvedMeasurementCapability)

    def test_no_task_specific_import_remains_in_the_module(self):
        """The module must not reach for a task's dataset constant.

        Checked through the AST, not the text. This module's own docstring
        NAMES `TIDMAD_DATA_DIR` while explaining the defect it removes, so a
        substring search matches the prose and fails on a module that is
        entirely correct -- which is exactly what happened when this test
        was first written. Imports are the thing to assert on; commentary
        about imports is not.
        """
        import ast
        from pathlib import Path

        import core.runtime_control.measurement_capability as mod

        tree = ast.parse(Path(mod.__file__).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)

        offenders = sorted(
            name
            for name in imported
            if "data_paths" in name or "dataset_config" in name or "TIDMAD" in name
        )
        assert offenders == [], (
            f"generic measurement capability imports task-owned modules: {offenders}"
        )

    def test_the_task_identity_is_carried_not_assumed(self):
        """Two tasks resolve to two capabilities. If the module had a
        default task, they would not."""
        a = resolve_measurement_capability(**IDENTITY, dataset_root=None)
        b = resolve_measurement_capability(
            task_identity="some_other_task",
            dataset_adapter="other_adapter",
            data_shape_class="other_shape",
            dataset_root=None,
        )
        assert a.task_identity != b.task_identity
        assert a.dataset_adapter != b.dataset_adapter
