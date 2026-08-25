"""F-12d-34 — the three engine sites that read a SampleSet that may be absent.

F-12d-27 made ``run_experiment_streaming`` admit ``sample_set=None``, because a
COMPOSED run trains from its transported task scope and carries no legacy
SampleSet by construction. The dispatch was widened; three sites downstream of
it still read the value as though it were always a dict. CI pyright named all
three (``reportOptionalIterable`` + two ``reportOptionalMemberAccess``), and
they are not one defect repeated — they differ in whether the absent case is
REACHABLE:

  * ``_setup_storage_provenance`` — REACHABLE TODAY. A composed TIDMAD run has
    a profile that DOES declare TIDMAD topology and a task scope that carries
    its own file identity, so it passes the ``declares_tidmad_topology`` guard
    and then read ``sample_set.keys()`` on ``None``. Any composed run with a
    runtime session would have died with ``AttributeError`` inside the RT2-B
    setup window. That is the defect this module exists for.

  * ``validate_ordering_against_scope`` and ``_regime_a_train_scope`` — not
    reachable today, and the tests below say so rather than implying a live
    hazard. They assert the REFUSAL, whose value is that the invariant is
    stated where the value is consumed: delete either guard and the failure
    becomes ``'NoneType' is not iterable`` from inside a set comprehension, or
    a ``TidmadScope`` built around nothing that fails several frames later.
"""

import pytest

from execute_tools import train_engine_sandbox as tes


def _tidmad_profile():
    """A profile that DOES declare TIDMAD topology (the reachable case)."""
    from execute_tools.dataset_config import resolve_dataset_profile

    return resolve_dataset_profile()


class TestStorageProvenanceWithNoSampleSet:
    """The reachable one: composed TIDMAD, topology declared, no SampleSet."""

    def test_absent_sample_set_reports_root_only_instead_of_crashing(self, tmp_path):
        profile = _tidmad_profile()
        assert tes.declares_tidmad_topology(profile), (
            "this test is only meaningful while the profile passes the topology "
            "guard — that is what carried execution into the per-file branch"
        )

        provenance = tes._setup_storage_provenance(str(tmp_path), None, profile)

        # Root-only: no per-file claim is invented for a scope this function
        # cannot see, and the root it DOES know is still reported.
        assert provenance["file_count"] == 0, (
            "a run whose per-file identity lives in a transported task scope "
            "must report no per-file claim, never guess one"
        )
        assert provenance["dataset_root"] == str(tmp_path)

    def test_a_present_sample_set_still_enumerates_its_files(self, tmp_path):
        """The TIDMAD path is unchanged — the new branch is additive.

        One scope file, and the scoped-byte estimate is the F2 sparse figure
        (2 PSD segments × 3 bytes/sample), NOT the on-disk size — the file
        does not exist under ``tmp_path``, which is what makes the two
        quantities distinguishable here.
        """
        profile = _tidmad_profile()
        provenance = tes._setup_storage_provenance(str(tmp_path), {"4": [0, 1]}, profile)
        assert provenance["file_count"] == 1
        assert provenance["files_present"] == 0
        assert provenance["total_file_bytes"] == 0
        assert provenance["expected_raw_bytes"] > 0


class TestOrderingRefusesWithoutAScope:
    def test_sequential_file_order_without_a_sample_set_is_refused(self):
        with pytest.raises(ValueError, match="no sample set to order against"):
            tes.validate_ordering_against_scope("sequential", [4, 5], None)

    def test_the_absent_scope_is_refused_only_when_an_order_needs_checking(self):
        """No file order means nothing to validate — absence is not an error."""
        tes.validate_ordering_against_scope("sequential", None, None)
        tes.validate_ordering_against_scope("shuffle", None, None)


class TestRegimeATrainScopeRefusesWithoutASampleSet:
    def test_no_task_scope_and_no_sample_set_is_refused(self):
        with pytest.raises(ValueError, match="nothing to train from"):
            tes._regime_a_train_scope(None, 1024, _tidmad_profile())
