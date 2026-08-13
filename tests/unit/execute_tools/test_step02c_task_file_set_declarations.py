"""Step 02c C2 — the two task-owned file-set declarations, and the exact
shape in which the health-peek one reaches the config.

Design: ``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/
pr_02c_systematic_groups.md`` §2, §8, §8.1, §11.2.

Two things are pinned here that nothing else can pin:

1. **A declared file set must be legal for the topology it is declared
   against.** ``DatasetProfile`` is the only place that can check this —
   the indices and ``num_files`` are sibling fields, so neither sub-model
   sees both. The three rejections (empty, duplicate, out-of-range) are
   validator LOGIC, not a type declaration: ``list[int]`` accepts every
   one of them.

2. **The §8.1 injection shape.** The declared health-peek set must reach
   ONLY the three blocking checks that already carry ``peek_file_indices``
   in the shipped YAML. The three recording checks ship no such key and
   evaluate every file; injecting the declaration there would narrow them
   from 20 files to 3 — a HealthGate POLICY change made while nominally
   only moving an authority. That is the single sharpest hazard in 02c,
   and it is invisible to every other test in the suite: the recording
   checks' own tests would still pass, because a three-file population is
   perfectly self-consistent.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from execute_tools.dataset_config import TIDMAD_PROFILE, DatasetProfile
from execute_tools.health_checks.config import (
    TASK_HEALTH_PEEK,
    CheckRef,
    clear_health_gates_config_cache,
    load_health_gates_config,
)

SHIPPED_CONFIGS = [
    "configs/health_checks.yaml",
    "configs/health_checks_baseline_observe_mode.yaml",
]

DECLARED_FILE_SET_FIELDS = ["anchor_selection_files", "health_peek_files"]


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_health_gates_config_cache()
    yield
    clear_health_gates_config_cache()


class TestDeclaredFileSetsMustBeLegalForTheTopology:
    """One concept, asserted across BOTH declarations.

    Written per-concept rather than per-field on purpose: the rule is
    "a declared file set indexes files this dataset actually has", and a
    per-field test cannot express that a future third declaration must
    obey it too.
    """

    @pytest.mark.parametrize("field", DECLARED_FILE_SET_FIELDS)
    @pytest.mark.parametrize(
        ("case", "value", "expected_fragment"),
        [
            ("empty", [], "is empty"),
            ("duplicate", [3, 3, 10], "duplicate indices"),
            ("above_range", [0, 20], "does not have"),
            ("negative", [-1, 3], "does not have"),
        ],
    )
    def test_illegal_membership_is_rejected(self, field, case, value, expected_fragment):
        payload = {**TIDMAD_PROFILE.model_dump(), field: value}
        with pytest.raises(ValidationError) as excinfo:
            DatasetProfile.model_validate(payload)
        message = str(excinfo.value)
        assert expected_fragment in message, f"{field}/{case}: unhelpful message {message!r}"
        assert field in message, f"{field}/{case}: the message must name the offending field"

    @pytest.mark.parametrize("field", DECLARED_FILE_SET_FIELDS)
    def test_legality_is_judged_against_this_dataset_not_tidmad(self, field):
        """File 19 is legal under TIDMAD's 20 files and illegal under a
        5-file dataset. If the bound topology were ignored, a task would
        silently declare files it cannot open."""
        narrow = TIDMAD_PROFILE.dataset.model_copy(update={"num_files": 5})
        payload = {
            **TIDMAD_PROFILE.model_dump(),
            "dataset": narrow.model_dump(),
            "anchor_selection_files": [0, 2, 4],
            "health_peek_files": [1, 3],
        }
        # Legal for this narrower dataset.
        DatasetProfile.model_validate(payload)
        with pytest.raises(ValidationError, match="num_files=5"):
            DatasetProfile.model_validate({**payload, field: [0, 19]})

    def test_the_shipped_tidmad_declarations_are_exact(self):
        """Stage-A compatibility: the migration must not move a value."""
        assert TIDMAD_PROFILE.anchor_selection_files == [0, 10, 19]
        assert TIDMAD_PROFILE.health_peek_files == [3, 10, 17]


class TestDeclaredHealthPeekInjectionShape:
    """§8.1 — the declaration reaches the key-carrying sites and NO others."""

    @pytest.mark.parametrize("config_path", SHIPPED_CONFIGS)
    def test_only_key_carrying_checks_receive_the_declaration(self, config_path):
        cfg = load_health_gates_config(config_path)

        resolved: dict[str, object] = {}
        for gate in cfg.health_gates:
            for check in gate.checks:
                resolved[gate.id] = check.config.get("peek_file_indices")

        blocking = {gid: v for gid, v in resolved.items() if gid.endswith("_blocking")}
        recording = {gid: v for gid, v in resolved.items() if gid.endswith("_recording")}
        assert blocking and recording, "the shipped config must exercise both roles"

        for gate_id, value in blocking.items():
            assert value == TIDMAD_PROFILE.health_peek_files, (
                f"{gate_id} did not resolve the declared health-peek set"
            )

        for gate_id, value in recording.items():
            assert value is None, (
                f"{gate_id} gained a peek_file_indices key it does not ship. The "
                f"declaration leaked into the keyless path, which narrows this "
                f"recording gate from every file to {value} — a HealthGate policy "
                f"change, not an authority change"
            )

    def test_resolution_is_idempotent_for_an_explicit_list(self):
        """An operator's explicit list is taken verbatim — resolving twice
        must not rewrite it into the declared default."""
        explicit = CheckRef(name="output_diversity", config={"peek_file_indices": [4, 7, 9]})
        again = CheckRef.model_validate(explicit.model_dump())
        assert explicit.config["peek_file_indices"] == [4, 7, 9]
        assert again.config["peek_file_indices"] == [4, 7, 9]

    def test_an_unrecognized_marker_is_rejected_not_iterated(self):
        """Left unvalidated, a typo'd marker is a truthy string and the
        blocking resolver would iterate it CHARACTER by character, peeking
        file indices like ``'t'``. A wrong answer, silently."""
        with pytest.raises(ValidationError, match="not a recognized marker"):
            CheckRef(name="output_diversity", config={"peek_file_indices": "task_helth_peek"})

    def test_the_marker_resolves_to_the_bound_declaration(self):
        ref = CheckRef(name="output_diversity", config={"peek_file_indices": TASK_HEALTH_PEEK})
        assert ref.config["peek_file_indices"] == TIDMAD_PROFILE.health_peek_files
        assert ref.config["peek_file_indices"] is not TIDMAD_PROFILE.health_peek_files, (
            "the resolved value must be a copy — a shared list would let a "
            "consumer mutate the shipped profile's declaration"
        )


class TestTheDeclarationsAreActuallyTheAuthority:
    """Reachability under a NON-TIDMAD declaration.

    Every other assertion in this file is satisfied just as well by the
    literals these declarations replaced, because under TIDMAD the
    declaration and the literal are the same three numbers. Only a profile
    that declares something ELSE can tell "reads the declaration" apart
    from "still hardcodes TIDMAD's answer".

    These were added because the C2 mutation
    ``files = list(profile.anchor_selection_files)`` -> ``files = [0,10,19]``
    SURVIVED the rest of the suite (ledger §24.8). Topology is held at
    TIDMAD throughout — only the declaration varies.
    """

    def test_anchor_selection_reads_the_supplied_declaration(self):
        from execute_tools.sample_set_builder import build_sample_set

        declared = [1, 5, 12]
        profile = TIDMAD_PROFILE.model_copy(update={"anchor_selection_files": declared})
        sample_set = build_sample_set(
            is_trial=True,
            trial_strategy="anchors",
            trial_portion=0.05,
            seed=42,
            profile=profile,
        )
        assert sorted(sample_set) == sorted(declared), (
            "the anchors strategy did not follow the profile's declared "
            "anchor_selection_files — it is still reading a literal"
        )

    def test_blocking_peeks_read_the_bound_declaration(self):
        from execute_tools.dataset_config import bind_dataset_profile

        declared = [2, 8, 14, 18]
        profile = TIDMAD_PROFILE.model_copy(update={"health_peek_files": declared})
        # An EXPLICIT path — ``load_health_gates_config`` only caches the
        # default path, so this cannot serve a config resolved under a
        # different profile.
        with bind_dataset_profile(profile):
            cfg = load_health_gates_config("configs/health_checks.yaml")

        for gate in cfg.health_gates:
            for check in gate.checks:
                resolved = check.config.get("peek_file_indices")
                if gate.id.endswith("_blocking"):
                    assert resolved == declared, (
                        f"{gate.id} resolved {resolved} instead of the bound "
                        f"task's declared health-peek set {declared}"
                    )
                else:
                    assert resolved is None, (
                        f"{gate.id} gained a peek list under a contrast declaration"
                    )
