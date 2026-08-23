"""PR-02c C4 — Stage B, rung 4.8-C: task-owned FILE-SET semantics.

Design: ``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/
pr_02c_systematic_groups.md`` §11.4, §19.

Stage A proved every TIDMAD identity is byte-identical. That is parity
evidence, and parity evidence can never prove an authority moved: under
TIDMAD each declaration holds exactly the numbers the literal it replaced
held, so "reads the declaration" and "still hardcodes TIDMAD's answer"
produce the same output. This rung is the only thing that separates them.

**Two atomic subcases, not one combined fixture.**

    C-anchor   vary ONLY anchor_selection_files   -> anchors follow;
                                                    blocking peeks UNCHANGED
    C-health   vary ONLY health_peek_files        -> blocking peeks and the
                                                    campaign trigger follow;
                                                    anchors UNCHANGED;
                                                    recording gates UNCHANGED

The **unvaried** assertion in each subcase is what carries the weight. A
single fixture varying both declarations and checking both consumers
followed could not distinguish "each consumer reads its own declaration"
from "one reads it and the other coincidentally agrees" (§19).

**Cardinality varies too, not only membership.** A contrast of
``[0,10,19] -> [1,5,9]`` is still three files, and would pass against a
consumer that silently assumes a triplet. C-anchor uses FIVE files and
C-health uses TWO, so the rung varies the semantic rather than swapping
one TIDMAD-shaped list for another.

**Held fixed throughout**: topology (``num_files`` stays 20), geometry,
encoding, channel identity, DataScope, strategy, seed, portion, metric
and model semantics. Atomicity is machine-checked against the TIDMAD
declaration, not promised in prose. 02b's ``num_files`` contrast is
deliberately NOT reused — it re-answers another child's question.

**All-files is NOT a third axis here.** It derives from topology (§2.3);
its genericity is proved as derived reachability in
``tests/unit/execute_tools/health_checks/test_step02c_derived_all_files.py``.
"""

from __future__ import annotations

import pytest

from core.campaign_artifacts import validate_experiment_completeness
from execute_tools.dataset_config import (
    TIDMAD_PROFILE,
    bind_dataset_profile,
    tidmad_topology,
)
from execute_tools.health_checks.config import (
    clear_health_gates_config_cache,
    load_health_gates_config,
)
from execute_tools.sample_set_builder import build_sample_set

SHIPPED_CONFIG = "configs/health_checks.yaml"

# Different CARDINALITY from TIDMAD's three, in both directions.
C_ANCHOR_FILES = [2, 7, 11, 15, 18]  # five
C_HEALTH_FILES = [6, 13]  # two

_PER_FILE_ERROR_MARKER = "missing per-file entries"


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_health_gates_config_cache()
    yield
    clear_health_gates_config_cache()


def _c_anchor_profile():
    return TIDMAD_PROFILE.model_copy(update={"anchor_selection_files": C_ANCHOR_FILES})


def _c_health_profile():
    return TIDMAD_PROFILE.model_copy(update={"health_peek_files": C_HEALTH_FILES})


def _diff_paths(left, right, prefix=""):
    """Dotted paths at which two nested dicts differ (02b B4 convention)."""
    paths = []
    for key in sorted(set(left) | set(right)):
        path = f"{prefix}{key}"
        lv, rv = left.get(key), right.get(key)
        if isinstance(lv, dict) and isinstance(rv, dict):
            paths.extend(_diff_paths(lv, rv, prefix=f"{path}."))
        elif lv != rv:
            paths.append(path)
    return paths


def _resolved_peeks(profile) -> dict[str, object]:
    """gate id -> resolved peek_file_indices, through the SHIPPED roster.

    Step 08b C5: the peek set is declared by the TASK's own health config,
    not derived from the bound ``DatasetProfile``, so the declaration is
    substituted where it now lives. The claim under test is unchanged — a
    declared set must reach exactly the blocking gates — and it is still
    made against production's real roster.
    """
    from tests.helpers.health_task_config import resolved_peek_files

    return resolved_peek_files(list(profile.health_peek_files))


def _anchor_population(profile) -> list[int]:
    return sorted(
        build_sample_set(
            is_trial=True,
            trial_strategy="anchors",
            trial_portion=0.05,
            seed=42,
            profile=profile,
        )
    )


def _campaign_enforces(profile, files_requested: list[int]) -> bool:
    record = {
        "denoising_score": -1.0,
        "file_vector": [1.0] * 20,
        "checkpoint_path": "/checkpoint.pth",
        "params": {"model_config": {"channels": 8}},
        "health_gate_results": [
            {
                "gate_name": "output_diversity_blocking",
                "execution_status": "passed",
                "resolved_action": "continue",
                "aggregation": {"files_requested": files_requested},
                "metrics": {"aggregate_statistics": {"count": 3}, "per_file": {}},
            }
        ],
    }
    with bind_dataset_profile(profile):
        # Step 10 / P1 (S7): the declared peek set is the caller's explicit
        # argument now. It comes from the SAME contrast profile this case
        # binds, so what the test asserts is unchanged — the declaration
        # drives the trigger — while the validator no longer reaches for a
        # profile of its own.
        errors = validate_experiment_completeness(
            record,
            configured_gate_ids=["output_diversity_blocking"],
            declared_health_peek=list(profile.health_peek_files),
        )
    return any(_PER_FILE_ERROR_MARKER in error for error in errors)


# ---------------------------------------------------------------------------
# The fixtures are atomic — machine-checked, not promised
# ---------------------------------------------------------------------------


class TestTheContrastFixturesAreAtomic:
    @pytest.mark.parametrize(
        ("subcase", "profile_fn", "expected_axis"),
        [
            ("C-anchor", _c_anchor_profile, "anchor_selection_files"),
            ("C-health", _c_health_profile, "health_peek_files"),
        ],
    )
    def test_exactly_one_declaration_differs(self, subcase, profile_fn, expected_axis):
        differing = _diff_paths(TIDMAD_PROFILE.to_wire(), profile_fn().to_wire())
        assert differing == [expected_axis], (
            f"{subcase} varies {differing}; it must vary {expected_axis!r} ALONE. "
            f"If one axis cannot be made meaningful, the declaration model is "
            f"wrong — STOP and report rather than adding a second axis."
        )

    @pytest.mark.parametrize(
        ("subcase", "declared"),
        [("C-anchor", C_ANCHOR_FILES), ("C-health", C_HEALTH_FILES)],
    )
    def test_the_contrast_varies_cardinality_not_just_membership(self, subcase, declared):
        """A same-size contrast would pass against a consumer that assumes
        a triplet, so the rung would prove less than it appears to."""
        assert len(declared) != 3, (
            f"{subcase} declares {len(declared)} files — TIDMAD's declarations "
            f"are both triplets, so a three-file contrast cannot detect a "
            f"consumer that hardcodes the count"
        )

    def test_topology_is_held_at_tidmad_in_both_subcases(self):
        """02b already proved a contrast topology travels; re-varying it
        here would re-answer 02b's question and drag in the Step-10
        residue §12.1 deliberately avoids."""
        for profile in (_c_anchor_profile(), _c_health_profile()):
            assert tidmad_topology(profile).dataset == tidmad_topology(TIDMAD_PROFILE).dataset


# ---------------------------------------------------------------------------
# C-anchor
# ---------------------------------------------------------------------------


class TestCAnchor:
    def test_the_anchors_strategy_follows_the_declaration(self):
        assert _anchor_population(_c_anchor_profile()) == sorted(C_ANCHOR_FILES)

    def test_the_blocking_peeks_are_UNCHANGED(self):
        """The half that makes this evidence rather than a coincidence.

        If both consumers moved when only the anchor declaration changed,
        they would be reading one shared value — which is exactly the
        merged "group map" §2.4 forbids.
        """
        resolved = _resolved_peeks(_c_anchor_profile())
        for gate_id, value in resolved.items():
            if gate_id.endswith("_blocking"):
                assert value == TIDMAD_PROFILE.health_peek_files, (
                    f"{gate_id} moved when only the ANCHOR declaration changed"
                )
            else:
                assert value is None, f"{gate_id} gained a peek key"

    def test_the_campaign_trigger_is_UNCHANGED(self):
        assert _campaign_enforces(_c_anchor_profile(), TIDMAD_PROFILE.health_peek_files)


# ---------------------------------------------------------------------------
# C-health
# ---------------------------------------------------------------------------


class TestCHealth:
    def test_the_blocking_monitored_files_follow_the_declaration(self):
        resolved = _resolved_peeks(_c_health_profile())
        for gate_id, value in resolved.items():
            if gate_id.endswith("_blocking"):
                assert value == C_HEALTH_FILES, (
                    f"{gate_id} resolved {value} instead of the declared {C_HEALTH_FILES}"
                )

    def test_the_recording_gates_are_UNCHANGED(self):
        """§8.1's leak guard, restated under a contrast declaration.

        The recording gates ship no ``peek_file_indices`` and must keep
        evaluating every file. If the declaration reached them they would
        narrow from 20 files to 2 — a HealthGate policy change.
        """
        resolved = _resolved_peeks(_c_health_profile())
        for gate_id, value in resolved.items():
            if gate_id.endswith("_recording"):
                assert value is None, (
                    f"{gate_id} received the declared health-peek set. It ships "
                    f"no such key and evaluates every file; narrowing it to "
                    f"{value} is a policy change, not an authority change"
                )

    def test_the_campaign_trigger_follows_the_declaration(self):
        profile = _c_health_profile()
        assert _campaign_enforces(profile, C_HEALTH_FILES)
        assert not _campaign_enforces(profile, TIDMAD_PROFILE.health_peek_files), (
            "TIDMAD's triplet still triggers enforcement under a task that declares something else"
        )

    def test_the_campaign_POLICY_matrix_is_unchanged(self):
        """Authority moved; policy did not. A reordered copy of the
        DECLARED set must still take the silent else-branch."""
        reordered = [C_HEALTH_FILES[1], C_HEALTH_FILES[0]]
        assert sorted(reordered) == sorted(C_HEALTH_FILES) and reordered != C_HEALTH_FILES
        assert not _campaign_enforces(_c_health_profile(), reordered)

    def test_the_anchors_population_is_UNCHANGED(self):
        assert _anchor_population(_c_health_profile()) == sorted(
            TIDMAD_PROFILE.anchor_selection_files
        )
