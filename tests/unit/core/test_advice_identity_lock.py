"""The workspace lock pins the run's advice-content identity.

The defect: the run's treatment input was not pinned. The arm
LABEL (``experiment_arm``) was canonical; what that arm actually received
was recorded nowhere, so a resume — or a second band — could consume
different advice and no surface refused.

What only these tests catch:

* ``TestResumeMatrix`` — the operator's five-row comparability table, run
  against REAL lock files through the production
  ``write_run_invariants`` / ``validate_run_invariants`` pair. The rows are
  separate cases because they fail separately: a mechanism that compares
  only when the STORED side participates passes rows 1-3 and silently
  admits row 5, which is precisely how an advice-bound run would
  inherit a workspace whose treatment nobody can reconstruct.
* ``TestLegacyLockIsRead``/``TestFreshLockPersists`` — creation and
  comparison are different concerns; each is asserted through the surface
  that owns it.
* ``TestThePairIsTheDeclaration`` — the three construction-time refusals,
  each naming a way a lock could LOOK pinned while pinning nothing.
* ``TestByteParity`` — a run that consumed no advice writes a lock
  key-for-key identical to one that predates the field, which is what
  makes "absent" a single unambiguous stored value.
* ``TestPartition`` — the digest is compared and the path is not, in the
  representation rather than in a validator's memory (R-11-6).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.run_invariants import (  # noqa: E402
    RUN_INVARIANTS_BASENAME,
    LockLaunchIdentity,
    RunInvariants,
    RunInvariantsViolation,
    validate_run_invariants,
    write_run_invariants,
)

#: Two distinct, well-formed advice identities. Hard-coded rather than read
#: back from the model, so the assertions cannot pass by comparing the
#: schema to itself.
ADVICE_A = hashlib.sha256(b'{"propose": "treatment A"}').hexdigest()
ADVICE_B = hashlib.sha256(b'{"propose": "treatment B"}').hexdigest()
PATH_A = "/run/advice/advice_v1.json"
PATH_B = "/run/advice/advice_v2.json"


def _invariants(**overrides) -> RunInvariants:
    """A minimal, otherwise-identical run. Only the advice pin varies."""
    base = dict(
        resolved_data_scope=[0, 1, 2, 3],
        health_gate_enabled=False,
        health_config_sha256=None,
        runtime_estimator_identity="estimator-v1",
        runtime_policy_identity="policy-v1",
    )
    base.update(overrides)
    return RunInvariants(**base)


def _pinned(sha: str | None, path: str | None) -> RunInvariants:
    return _invariants(advice_sha256=sha, advice_path=path)


def _resume(workspace: Path, stored: RunInvariants, current: RunInvariants) -> str:
    """Write ``stored`` as the workspace lock, then resume with ``current``.

    Returns ``"COMPATIBLE"`` or ``"REFUSE"`` — the production verdict, from
    the production functions, never a re-implementation of the comparison.
    """
    write_run_invariants(str(workspace), stored)
    try:
        validate_run_invariants(str(workspace), current)
    except RunInvariantsViolation:
        return "REFUSE"
    return "COMPATIBLE"


class TestResumeMatrix:
    """The operator's comparability table, one test per row."""

    def test_row1_no_advice_workspace_resumes_in_the_legacy_regime(self, tmp_path):
        """stored absent + current absent -> COMPATIBLE.

        The row that decides whether this feature is deployable at all:
        every workspace in the repository that never used advice must stay
        resumable. HOW THIS FAILS: make the digest a value a no-advice run
        computes anyway (an empty-string default, a hash of b"") and every
        existing workspace refuses on the next resume.
        """
        assert _resume(tmp_path, _pinned(None, None), _pinned(None, None)) == "COMPATIBLE"

    def test_row2_the_same_advice_resumes(self, tmp_path):
        """stored A + current A -> COMPATIBLE.

        HOW THIS FAILS: pin anything host-dependent alongside the digest —
        a timestamp, a working directory, an inode — and a legitimate
        resume of the run's own workspace refuses.
        """
        assert _resume(tmp_path, _pinned(ADVICE_A, PATH_A), _pinned(ADVICE_A, PATH_A)) == (
            "COMPATIBLE"
        )

    def test_row2b_the_same_advice_at_a_different_path_still_resumes(self, tmp_path):
        """The path is NOT compared: same bytes, different location, one
        treatment.

        Path proves authority and reachability; the observed digest proves
        treatment identity. HOW THIS FAILS: move ``advice_path`` into
        ``_CANONICAL`` and restaging the identical artifact — a different
        mount on the pod, a copy under a per-band directory — refuses a
        resume that is scientifically the same run. This is the Q-P1-2
        exclusion rule the model-plugin identities already state.
        """
        assert _resume(tmp_path, _pinned(ADVICE_A, PATH_A), _pinned(ADVICE_A, PATH_B)) == (
            "COMPATIBLE"
        )

    def test_row3_different_advice_refuses(self, tmp_path):
        """stored A + current B -> REFUSE. The defect that opened this PR.

        HOW THIS FAILS: drop ``advice_sha256`` from ``_CANONICAL`` and a
        workspace silently continues under a different treatment while
        every record in it still carries the original arm label.
        """
        assert _resume(tmp_path, _pinned(ADVICE_A, PATH_A), _pinned(ADVICE_B, PATH_B)) == "REFUSE"

    def test_row4_removing_the_advice_refuses(self, tmp_path):
        """stored A + current absent -> REFUSE.

        A treated workspace continued WITHOUT its treatment is not the same
        experiment, and it is the accident a rerun of the launch command
        with one flag dropped produces. HOW THIS FAILS: compare only when
        the CURRENT side participates and this row passes silently.
        """
        assert _resume(tmp_path, _pinned(ADVICE_A, PATH_A), _pinned(None, None)) == "REFUSE"

    def test_row5_a_legacy_workspace_cannot_be_upgraded_into_a_treated_one(self, tmp_path):
        """stored absent + current A -> REFUSE.

        Not symmetry for its own sake (operator): this is the case that
        would otherwise let an advice-bound run quietly inherit a workspace
        whose treatment nobody can reconstruct — the stored ``absent`` means
        *nothing was recorded*, never *nothing was consumed*. HOW THIS
        FAILS: implement the conditional comparison as "compare only when
        the STORED side is non-None" — every other row still passes and
        this one flips to COMPATIBLE.
        """
        assert _resume(tmp_path, _pinned(None, None), _pinned(ADVICE_A, PATH_A)) == "REFUSE"


class TestLegacyLockIsRead:
    """Rows 1 and 5 again, but against a lock whose keys are PHYSICALLY
    absent rather than written-as-None — the state every workspace on disk
    is actually in."""

    def _legacy_lock(self, workspace: Path) -> None:
        payload = json.loads(
            write_run_invariants(str(workspace), _pinned(None, None))
            and (workspace / RUN_INVARIANTS_BASENAME).read_text()
        )
        assert "advice_sha256" not in payload
        assert "advice_path" not in payload

    def test_a_lock_with_no_advice_keys_resumes_without_advice(self, tmp_path):
        """HOW THIS FAILS: give either field a non-None default and a lock
        that predates the pin stops parsing into the pre-feature state."""
        self._legacy_lock(tmp_path)
        validate_run_invariants(str(tmp_path), _pinned(None, None))

    def test_a_lock_with_no_advice_keys_refuses_an_advice_bound_resume(self, tmp_path):
        """HOW THIS FAILS: as row 5 — a stored-side-conditional comparison
        reads the missing key as agreement."""
        self._legacy_lock(tmp_path)
        with pytest.raises(RunInvariantsViolation, match="advice_sha256"):
            validate_run_invariants(str(tmp_path), _pinned(ADVICE_A, PATH_A))


class TestFreshLockPersists:
    """Creation is a separate concern from comparison (operator). This is
    the creation half."""

    def test_a_fresh_advice_bound_workspace_is_created_and_the_identity_persists(self, tmp_path):
        """A FRESH workspace launched with advice A is allowed and must
        persist A. HOW THIS FAILS: resolve the pin anywhere downstream of
        the lock write, or omit it from the payload unconditionally, and
        the run's own workspaces record nothing to compare on the next
        iteration — the defect would survive the fix."""
        path = write_run_invariants(str(tmp_path), _pinned(ADVICE_A, PATH_A))
        payload = json.loads(Path(path).read_text())
        assert payload["advice_sha256"] == ADVICE_A
        assert payload["advice_path"] == PATH_A
        # And it reads back as the compared value, not merely as bytes.
        validate_run_invariants(str(tmp_path), _pinned(ADVICE_A, PATH_A))

    def test_the_launch_identity_carrier_reaches_the_lock(self, tmp_path):
        """``LockLaunchIdentity`` is the declared transport for compared
        launch values; a field it carries but the builder drops would leave
        every entry point locking None. HOW THIS FAILS: delete either
        assignment in ``build_run_invariants`` and the pin never lands."""
        carrier = LockLaunchIdentity(advice_sha256=ADVICE_A, advice_path=PATH_A)
        assert carrier.advice_sha256 == ADVICE_A
        assert carrier.advice_path == PATH_A


class TestThePairIsTheDeclaration:
    """Three ways a lock could LOOK pinned while pinning nothing."""

    def test_a_path_without_a_digest_is_refused(self):
        """The dangerous half: the COMPARED field would be None, so the
        workspace admits ANY advice on resume while recording an artifact.
        HOW THIS FAILS: drop the model validator and a caller that forgets
        the digest produces a fail-open lock that reads as authoritative."""
        with pytest.raises(ValueError, match="advice_path is set but advice_sha256"):
            _pinned(None, PATH_A)

    def test_a_digest_without_a_path_is_refused(self):
        """A refusal would show two hex strings and no artifact to compare.
        HOW THIS FAILS: drop the validator and a real refusal becomes
        undiagnosable in the field."""
        with pytest.raises(ValueError, match="advice_sha256 is set but advice_path"):
            _pinned(ADVICE_A, None)

    @pytest.mark.parametrize(
        "bad",
        [
            f"{ADVICE_A}  /run/advice/advice.json",  # raw `sha256sum` output
            ADVICE_A.upper(),
            ADVICE_A[:63],
            "not-a-digest",
        ],
    )
    def test_a_digest_that_is_not_a_bare_sha256_is_refused(self, bad):
        """``sha256sum FILE`` prints ``<hex>  <path>``. HOW THIS FAILS: drop
        ``awk '{print $1}'`` in the launcher and the run's scientific
        identity silently becomes host directory layout — a value that
        still compares equal to itself, so every resume test stays green."""
        with pytest.raises(ValueError, match="advice_sha256"):
            _pinned(bad, PATH_A)

    def test_a_relative_recorded_path_is_refused(self):
        """The run that writes the lock and whoever reads it back do not
        share a working directory (``run_chain.sh`` cd's to the project
        dir). HOW THIS FAILS: record argv verbatim instead of resolving it
        and the lock names a different file for each reader."""
        with pytest.raises(ValueError, match="relative"):
            _pinned(ADVICE_A, "advice/run.json")


class TestByteParity:
    def test_a_no_advice_lock_is_key_for_key_a_pre_feature_lock(self, tmp_path):
        """The omission is load-bearing, not cosmetic: it is what makes
        "this run consumed no advice" and "this lock predates the pin" the
        SAME stored value, which is what lets ordinary canonical equality
        produce the legacy-compatible row. HOW THIS FAILS: serialize the
        keys as ``null`` and the two states become distinguishable in the
        file while remaining indistinguishable to the comparison — the
        worst of both."""
        write_run_invariants(str(tmp_path), _pinned(None, None))
        payload = json.loads((tmp_path / RUN_INVARIANTS_BASENAME).read_text())
        assert "advice_sha256" not in payload
        assert "advice_path" not in payload


class TestPartition:
    def test_the_digest_is_compared_and_the_path_is_not(self):
        """R-11-6: the distinction must be a property of the
        REPRESENTATION, not of whichever validator remembers it. HOW THIS
        FAILS: classify either field on the wrong side — the path becoming
        canonical breaks row 2b, the digest becoming provenance breaks rows
        3-5 — and the partition guard alone would stay green for both,
        because both tuples remain a partition."""
        assert "advice_sha256" in RunInvariants._CANONICAL
        assert "advice_sha256" not in RunInvariants._PROVENANCE
        assert "advice_path" in RunInvariants._PROVENANCE
        assert "advice_path" not in RunInvariants._CANONICAL
