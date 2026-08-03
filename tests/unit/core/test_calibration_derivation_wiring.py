"""The derivation is wired to the success path, and only there.

V20 PR C1 / C-C3c part 3.

Parts 1 and 2 built a converter and a persistence boundary. This proves
production uses them, and — equally important — proves it does **not** use
them where it must not.

THE STRUCTURAL RISK. `_append_runtime_observation` is the obvious hook and
the wrong one: it has four production call sites and three record failures —
a subprocess rejection, an evidence-channel failure and a wall-clock
timeout. Deriving there would feed failure evidence into throughput
calibration, which `calibration_policy.py:279-285` forbids and explicitly
anticipates ("should another producer ever record failure evidence as an
observation").

That finding came from an audit, and an audit finding with no test decays
into a comment somebody later removes. The guard below fails if the
derivation is moved into the shared helper.

THE SAFETY CONTRACT. System A is already persisted when the derivation runs.
Losing a calibration sample must never cost an attempt, so the helper is
total: it returns for any input, records the loss, and raises nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import nodes.ml_hyperparameter_tune_agent as tuner

SOURCE = Path(tuner.__file__).read_text()
TREE = ast.parse(SOURCE)

#: The three call sites that record FAILURES. Deriving calibration from any
#: of them would put a rejection, an infrastructure failure or a timeout into
#: throughput calibration.
FAILURE_PATH_FUNCTIONS = (
    "_handle_in_subprocess_rejection",
    "_raise_if_evidence_channel_failure",
    "_raise_if_wall_clock_timeout",
)

DERIVATION = "_derive_calibration_from_observation"


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in the tuner")


def _calls_within(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name:
                names.add(name)
    return names


class TestItIsWiredToTheSuccessPath:
    def test_the_derivation_is_called_in_production(self):
        """Reachability. Deleting the production hook fails here, so the
        converter cannot become another component built and never called —
        the shape of #156, #157, #159 and the A5 field-drop."""
        assert f"{DERIVATION}(" in SOURCE.replace(f"def {DERIVATION}(", ""), (
            "the calibration derivation is defined but never called from production"
        )

    def test_it_is_called_from_run(self):
        assert DERIVATION in _calls_within(_function("run"))

    def test_it_runs_after_the_system_a_append(self):
        """Ordering is the safety contract: System A is the source of truth
        and must be durable before the derived view is attempted."""
        append_at = SOURCE.index("_append_runtime_observation(\n                        sandbox")
        derive_at = SOURCE.index(f"{DERIVATION}(\n                        sandbox")
        assert append_at < derive_at, (
            "the derivation runs before System A is persisted; a crash "
            "between them would lose the raw measurement but keep the "
            "derived one"
        )


class TestItIsNotWiredToAnyFailurePath:
    """The audit finding, made permanent."""

    @pytest.mark.parametrize("name", FAILURE_PATH_FUNCTIONS)
    def test_no_failure_handler_derives_calibration(self, name):
        assert DERIVATION not in _calls_within(_function(name)), (
            f"{name} records a FAILURE. Deriving calibration there would put "
            "a rejection, infrastructure failure or timeout into throughput "
            "calibration, which calibration_policy forbids."
        )

    def test_the_shared_append_helper_does_not_derive(self):
        """The named structural guard. `_append_runtime_observation` is
        shared by the success path and all three failure paths, so moving
        the derivation into it would silently re-enable exactly what the
        audit found."""
        assert DERIVATION not in _calls_within(_function("_append_runtime_observation")), (
            "the derivation was moved into the shared append helper, whose "
            "four call sites include three failure paths"
        )

    def test_the_derivation_is_called_exactly_once_in_the_tuner(self):
        """One seam. A second call site would be a second policy about what
        counts as calibration evidence."""
        call_count = sum(
            1
            for node in ast.walk(TREE)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", getattr(node.func, "attr", None)) == DERIVATION
        )
        assert call_count == 1, f"expected one production call site, found {call_count}"


class TestLosingCalibrationNeverCostsAnAttempt:
    """Fail-open for the scientific workflow, fail-closed for calibration
    authority. System A is already persisted when this runs."""

    class _Sandbox:
        base_dir = "/tmp"

    @pytest.fixture(autouse=True)
    def _isolated_registry(self, tmp_path, monkeypatch):
        """Point the registry at a temporary root for every test here.

        These call the real production helper, which resolves the registry
        from `SIDERIUS_CALIBRATION_DIR` or `$HOME`. Without this, an input
        that PARSES -- `{"timestamp": "t"}` is a valid RuntimeObservation --
        gets far enough to create profiles in the operator's real tree.
        Caught exactly that way: a test run left a live
        `runtime_calibration_v2` directory behind.
        """
        monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))

    def test_a_none_observation_is_a_no_op(self):
        tuner._derive_calibration_from_observation(
            self._Sandbox(), rv_block=None, device_identity=None, data_dir=None
        )

    def test_an_unparseable_observation_does_not_raise(self, capsys):
        """A malformed block must not propagate into the attempt loop; the
        experiment result is already decided by this point."""
        tuner._derive_calibration_from_observation(
            self._Sandbox(),
            rv_block={"nonsense": 1},
            device_identity=None,
            data_dir=None,
        )
        assert "non-fatal" in capsys.readouterr().out

    def test_the_loss_is_reported_rather_than_swallowed(self, capsys):
        """Silent best-effort is how a subsystem comes to be believed
        working while producing nothing — which is what the 20-record,
        0-promotion registry turned out to be."""
        tuner._derive_calibration_from_observation(
            self._Sandbox(),
            rv_block={"nonsense": 1},
            device_identity=None,
            data_dir=None,
        )
        assert "[runtime_control] calibration" in capsys.readouterr().out

    def test_the_helper_is_total(self):
        """No input shape may escape as an exception."""
        for rv in (None, {}, {"nonsense": 1}, {"timestamp": "t"}):
            tuner._derive_calibration_from_observation(
                self._Sandbox(), rv_block=rv, device_identity=None, data_dir=None
            )


class TestIdentityIsNotFabricated:
    def test_a_missing_uuid_cannot_produce_an_eligible_identity(self):
        """`IdentityContext` refuses a blank field, so an absent device UUID
        yields `identity=None` and the derivation quarantines. The wiring
        must never substitute a placeholder to get past that."""
        from pydantic import ValidationError

        from core.runtime_control.calibration_derivation import IdentityContext

        with pytest.raises(ValidationError):
            IdentityContext(
                task_identity="t",
                data_shape_class="d",
                hardware_uuid="",
                runtime_stack_identity="s",
            )

    def test_the_wiring_guards_on_the_uuid_before_building_identity(self):
        """Source-level, because the alternative — a placeholder UUID — would
        produce an eligible record that looks measured and names the wrong
        device."""
        helper = _function(DERIVATION)
        code = ast.unparse(helper)
        assert "if uuid and" in code, (
            "the wiring must not construct an IdentityContext without a real device UUID"
        )
