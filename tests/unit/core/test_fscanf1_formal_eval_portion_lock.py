"""Two runs at different formal eval scopes are not one experiment.

F-SCANF-1 (release blocker). ``formal_eval_portion`` — the FRACTION of the
eval scope a FORMAL round scores over — was RECORDED as per-file-best
provenance (``execute_tools/per_file_best.py``: "from run_config; null for
legacy") and existed as a CLI argument, but was not a declared
``RunInvariants`` field at all: neither ``_CANONICAL`` (compared) nor
``_PROVENANCE`` (recorded-only), the two tuples that must PARTITION every
declared field. So two iterations whose formal evaluation covered different
fractions of the data folded into one incumbent with no refusal. Recorded
was not enforced, and frozen ``D-FAIL-7`` lists "train / eval portions"
among the values a resume must verify — its ``known_gap`` G4 names this
field by name.

THE RESUME-SEMANTICS CONSEQUENCE, stated where it is asserted. Adding a
CANONICAL field changes what an existing workspace's lock is compared
against, because ``validate_run_invariants`` is a bare ``!=`` over every
canonical name with NO None-skip and NO legacy tolerance, and a key absent
from a stored lock parses to the field's declared DEFAULT. The default is
therefore the whole decision:

    default 1.0 (chosen)   legacy lock parses to 1.0
                           -> a run at 1.0 resumes; a run at 0.1 REFUSES
    default None (rejected) legacy lock parses to None, and every entry
                           point resolves a real float
                           -> EVERY pre-existing workspace REFUSES

The residual this deliberately accepts: a legacy lock cannot distinguish
"ran at 1.0" from "predates the field", so a legacy workspace resumed at 1.0
is admitted. Making that distinguishable requires a conditional-comparison
surface, which ``core/run_invariants.py``'s ``advice_sha256`` block forbids
by name (R-11-6).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from core.run_invariants import (
    LockLaunchIdentity,
    RunInvariants,
    RunInvariantsViolation,
    ensure_run_invariants,
    validate_run_invariants,
    write_run_invariants,
)

BOUNDED_PORTION = 0.1  # any non-default qualification fraction exercises the lock


def _invariants(portion: float) -> RunInvariants:
    """A lock for a run declaring ``portion`` as its formal eval fraction."""
    return RunInvariants(
        resolved_data_scope=[0, 1, 2, 3],
        health_gate_enabled=False,
        health_config_sha256=None,
        runtime_estimator_identity="est-1",
        runtime_policy_identity="pol-1",
        formal_eval_portion=portion,
    )


class TestTheEvalFractionIsCompared:
    """The row's acceptance test: recorded is now enforced."""

    def test_a_second_run_at_a_different_fraction_refuses(self, tmp_path: Path) -> None:
        """FAILS silently (status "validated") before the fix.

        Two iterations, one workspace, formal evaluation over different
        fractions of the data. Their aggregate scalars are not one
        comparison, and the lock now says so.
        """
        workspace = str(tmp_path / "ws")
        assert ensure_run_invariants(workspace, _invariants(BOUNDED_PORTION)) == "created"

        with pytest.raises(RunInvariantsViolation) as exc:
            validate_run_invariants(workspace, _invariants(0.5))
        assert "formal_eval_portion" in str(exc.value)
        assert "locked=0.1" in str(exc.value)
        assert "this run=0.5" in str(exc.value)

    def test_the_same_fraction_resumes(self, tmp_path: Path) -> None:
        """The refusal is about DIVERGENCE, never about the field existing."""
        workspace = str(tmp_path / "ws")
        ensure_run_invariants(workspace, _invariants(BOUNDED_PORTION))

        assert ensure_run_invariants(workspace, _invariants(BOUNDED_PORTION)) == "validated"

    def test_it_is_compared_not_merely_recorded(self) -> None:
        """The declared partition, asserted as the concept it encodes."""
        assert "formal_eval_portion" in RunInvariants._CANONICAL
        assert "formal_eval_portion" not in RunInvariants._PROVENANCE


class TestTheLegacyWorkspaceConsequence:
    """What a lock written before this field does on resume."""

    @staticmethod
    def _write_legacy_lock(workspace: Path) -> None:
        """A lock with no ``formal_eval_portion`` key — the pre-fix bytes."""
        workspace.mkdir(parents=True)
        payload = json.loads(
            Path(write_run_invariants(str(workspace / "inner"), _invariants(1.0))).read_text(
                encoding="utf-8"
            )
        )
        assert "formal_eval_portion" not in payload
        (workspace / "run_invariants_lock.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    def test_a_legacy_workspace_resumed_at_the_default_is_admitted(self, tmp_path: Path) -> None:
        """The legacy regime, and the reason the default is 1.0."""
        workspace = tmp_path / "ws"
        self._write_legacy_lock(workspace)

        assert validate_run_invariants(str(workspace), _invariants(1.0)) is None

    def test_a_legacy_workspace_resumed_at_a_declared_fraction_refuses(
        self, tmp_path: Path
    ) -> None:
        """The deliberate, separately-justified half of the consequence.

        A pre-fix workspace carries no record of the fraction it evaluated,
        so a resume that DECLARES one cannot be proven comparable. It fails
        closed — which is the ``task_composition_fingerprint`` precedent, and
        no compatibility bypass may be added for it.
        """
        workspace = tmp_path / "ws"
        self._write_legacy_lock(workspace)

        with pytest.raises(RunInvariantsViolation, match="formal_eval_portion"):
            validate_run_invariants(str(workspace), _invariants(BOUNDED_PORTION))


class TestLegacyAndFullEvalLockBytesAreUnchanged:
    """Omitted at the default, like every optional canonical field."""

    def test_a_full_eval_lock_writes_no_key(self, tmp_path: Path) -> None:
        path = write_run_invariants(str(tmp_path / "ws"), _invariants(1.0))
        payload = json.loads(Path(path).read_text(encoding="utf-8"))

        assert "formal_eval_portion" not in payload

    def test_a_declared_fraction_writes_the_key(self, tmp_path: Path) -> None:
        """The omission must not swallow the value it exists to pin."""
        path = write_run_invariants(str(tmp_path / "ws"), _invariants(BOUNDED_PORTION))
        payload = json.loads(Path(path).read_text(encoding="utf-8"))

        assert payload["formal_eval_portion"] == BOUNDED_PORTION


class TestEveryParticipatingEntryPointThreadsIt:
    """A compared value must never arrive ambiently.

    Three entry points write a lock for a workspace whose runs share this
    value — the chain pre-flight and ``run_workflow`` write the SAME chain
    workspace, and the tuner writes its sub-workspace. If any one of them
    left the value on the builder default while another threaded the real
    one, the two would write contradictory locks and abort every campaign
    run at a non-default portion (the V19 PR 2 lock-collision failure mode).

    ``scripts/run_comparison.py`` is deliberately absent: it is the
    documented default caller, has no ``--formal_eval_portion`` argument at
    all, and its tuner child therefore runs at the same 1.0 default the
    builder resolves.
    """

    SITES: ClassVar[dict[str, str]] = {
        "src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py": (
            "formal_eval_portion=agent_input.formal_eval_portion,"
        ),
        "src/workflows/model_exploration.py": "formal_eval_portion=launch.formal_eval_portion,",
        "src/workflows/run_one_iteration.py": ("formal_eval_portion=args.formal_eval_portion,"),
    }

    def test_each_lock_site_threads_the_declared_value(self) -> None:
        repo = Path(__file__).resolve().parents[3]
        for relative, expected in self.SITES.items():
            source = (repo / relative).read_text(encoding="utf-8")
            assert expected in source, f"{relative} does not thread formal_eval_portion"

    def test_the_carrier_default_is_the_full_eval_value(self) -> None:
        """A caller that omits it gets a byte-identical lock."""
        assert LockLaunchIdentity().formal_eval_portion == 1.0
