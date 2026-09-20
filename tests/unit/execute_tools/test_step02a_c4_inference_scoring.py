"""PR-02a commit C4 — inference and scoring read the same declaration.

Design:
``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md``
§1 (the raw/denoised boundary), §5f (derived-artifact indexing), §6.4.

C4 finishes the data path: the two remaining subprocess entries take the
same transport C3 built, and the RAW validation filename — inlined at
eight production sites, two of them building it two different ways —
finally comes from ``validation_file_pattern``, the seam that shipped
with zero production consumers.

**The boundary this commit is most at risk of crossing.** ``scoring_utils``
handles the raw validation file AND the denoised deliverable in the same
functions. The raw name is Step-02-owned input topology; the denoised name
belongs to the Deliverable Contract, whose owner is still open. Several
tests below exist only to hold that line.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

import execute_tools.scoring_utils as su
from execute_tools.dataset_config import (
    TIDMAD_PROFILE,
    DatasetProfile,
    tidmad_topology,
)

# Repo root from THIS file's location, per the portability rule — never an
# absolute path, and never another clone.
REPO_ROOT = Path(__file__).resolve().parents[3]

# NOTE: denoising_score_single.py runs its argparse at MODULE level, so it
# cannot be imported in-process — importing it parses pytest's argv and exits.
# Its surface is therefore read from source here and exercised for real
# across a subprocess at Checkpoint C.


def _profile_with(pattern: str) -> DatasetProfile:
    return TIDMAD_PROFILE.model_copy(
        update={
            "dataset": tidmad_topology(TIDMAD_PROFILE).dataset.model_copy(
                update={"validation_file_pattern": pattern}
            )
        }
    )


@pytest.fixture
def captured_raw_names(monkeypatch):
    """Capture the raw filename the REAL scorer hands to the PSD reader."""
    seen: list[str] = []

    def fake_psd(file_path, files, ch, start=0):
        if ch == 2:
            seen.append(files)
        return np.zeros(4), np.zeros(4)

    monkeypatch.setattr(su, "get_one_sec_psd", fake_psd)
    monkeypatch.setattr(su, "get_snr", lambda freq, pwr, target=None: (1.0, 1.0))
    return seen


def _score(profile: DatasetProfile | None, file_index: int = 7):
    su.score_vector(
        data_dir=".",
        sample_set={file_index: [0]},
        anchor_map={str(file_index): [1.0]},
        s_max=1.0,
        denoised_filename_fn=lambda fi: "denoised.h5",
        raw_data_dir=".",
        parallel=False,
        profile=profile,
    )


# ---------------------------------------------------------------------------
# The dead seam is closed — and the scorer FOLLOWS the declaration
# ---------------------------------------------------------------------------


class TestRawValidationNameComesFromTheProfile:
    def test_the_scorer_reads_a_contrast_pattern(self, captured_raw_names):
        """§6.4's acceptance mutation, as a standing test: point the profile
        at a different validation pattern and the scorer must read the new
        name. This is what proves the name is no longer inlined.
        """
        _score(_profile_with("raw_{file_index:03d}.hdf5"))
        assert captured_raw_names == ["raw_007.hdf5"]
        assert not any("abra" in n for n in captured_raw_names)

    def test_tidmad_parity_is_preserved(self, captured_raw_names):
        """The same call under the shipped profile still produces the exact
        string the scorer used to inline."""
        _score(TIDMAD_PROFILE)
        assert captured_raw_names == ["abra_validation_0007.h5"]


# ---------------------------------------------------------------------------
# §5f — derived-artifact INDEXING, parity-only
# ---------------------------------------------------------------------------


class TestDerivedArtifactIndexing:
    """Disposition A: already generic, so C4 pins it rather than changing it.

    Deliverables are keyed by the INPUT identity (``file_index``) through a
    callable. That keying is Step-02-owned; the NAME the callable returns is
    the Deliverable Contract's.
    """

    def test_deliverables_are_keyed_by_input_identity(self, captured_raw_names):
        """``denoised_filename_fn`` is called with the file index, and with
        nothing else — the invariant §5f pins."""
        seen_keys: list[int] = []

        def namer(file_index):
            seen_keys.append(file_index)
            return f"denoised_{file_index}.h5"

        su.score_vector(
            data_dir=".",
            sample_set={3: [0], 11: [0]},
            anchor_map={"3": [1.0], "11": [1.0]},
            s_max=1.0,
            denoised_filename_fn=namer,
            raw_data_dir=".",
            parallel=False,
            profile=TIDMAD_PROFILE,
        )
        assert sorted(seen_keys) == [3, 11]

    def test_raw_and_denoised_names_are_resolved_by_different_authorities(self, captured_raw_names):
        """The two halves must not converge. Raw comes from the profile;
        denoised comes from the injected callable. A future change that
        routed the denoised name through the profile would be a
        Deliverable-Contract leak, and this is what would notice."""
        su.score_vector(
            data_dir=".",
            sample_set={5: [0]},
            anchor_map={"5": [1.0]},
            s_max=1.0,
            denoised_filename_fn=lambda fi: "SENTINEL_DELIVERABLE.h5",
            raw_data_dir=".",
            parallel=False,
            profile=_profile_with("raw_{file_index}.bin"),
        )
        assert captured_raw_names == ["raw_5.bin"]
        assert "SENTINEL_DELIVERABLE" not in captured_raw_names


class TestNoDeliverableContractLeakage:
    def test_the_profile_cannot_produce_a_denoised_name(self):
        """A blunt guard on §1's STOP condition. ``validation_file_name`` is
        the RAW input name; if a future edit pointed it at a denoised
        template, the scorer would read its own output as ground truth."""
        for i in (0, 7, 19):
            assert "denoised" not in tidmad_topology(TIDMAD_PROFILE).dataset.validation_file_name(i)

    def test_the_deliverable_write_path_is_untouched_by_the_profile(self):
        """``create_abra_file`` writes the denoised artifact. C4 must not have
        threaded the dataset profile into it — that contract has a different
        (still undecided) owner."""
        import execute_tools.array2h5 as array2h5

        source = inspect.getsource(array2h5)
        assert "dataset_profile" not in source
        assert "resolve_dataset_profile" not in source


# ---------------------------------------------------------------------------
# CP-A3 — all three entries take the SAME transport
# ---------------------------------------------------------------------------


class TestAllThreeEntriesShareOneTransport:
    """The operator's stated reason for keeping all three boundaries in one
    PR: a state where training reads the profile while scoring still reads
    constants is 'the same file decomposed two ways, silently'.
    """

    @pytest.mark.parametrize(
        ("module_path", "allows_uncomposed_profile"),
        [
            ("src/execute_tools/train_engine_sandbox.py", True),
            ("src/execute_tools/inference_single.py", True),
            ("src/execute_tools/denoising_score_single.py", False),
        ],
    )
    def test_each_entry_declares_the_flag_and_fails_closed(
        self, module_path, allows_uncomposed_profile
    ):
        source = (REPO_ROOT / module_path).read_text()
        if module_path == "src/execute_tools/train_engine_sandbox.py":
            from execute_tools.train_engine_sandbox import build_training_parser

            args = build_training_parser().parse_args(
                [
                    "--model_cfg",
                    "model.json",
                    "--train_cfg",
                    "train.json",
                    "--loss_cfg",
                    "loss.json",
                    "--dataset_profile_json",
                    "profile.json",
                ]
            )
            assert args.dataset_profile_json == "profile.json"
        else:
            assert '"--dataset_profile_json"' in source, f"{module_path} must expose the flag"
        assert "load_dataset_profile(" in source, f"{module_path} must fail closed on a bad path"
        if allows_uncomposed_profile:
            assert "resolve_dataset_profile()" in source, f"{module_path} must keep Regime-A"
        else:
            assert "resolve_dataset_profile()" not in source, (
                f"{module_path} must require the composed profile"
            )

    # Migrated production modules that read the RAW validation file.
    MIGRATED_ENTRIES: ClassVar[tuple[str, ...]] = (
        "src/execute_tools/train_engine_sandbox.py",
        "src/execute_tools/inference_single.py",
        "src/execute_tools/denoising_score_single.py",
        "src/execute_tools/scoring_utils.py",
    )

    @pytest.mark.parametrize("module_path", MIGRATED_ENTRIES)
    def test_no_migrated_entry_re_inlines_the_raw_validation_name(self, module_path):
        """Anti-regression, mirroring ``test_dataset_contract.py``'s
        training-name guard.

        This exists because a mutation SURVIVED without it: re-inlining
        ``f"abra_validation_{file_index:04d}.h5"`` in ``inference_single``
        left every other assertion green, since the flag, the loader and the
        resolver were all still present in the file. Checking that the
        transport EXISTS does not prove every read goes through it.

        DENOISED names are deliberately exempt — ``abra_validation_denoised_``
        is the Deliverable Contract's template and is NOT 02a's to move.
        """
        source = (REPO_ROOT / module_path).read_text()
        offenders = [
            line.strip()
            for line in source.splitlines()
            if re.search(r'f?"abra_validation_\{', line)
            and "denoised" not in line
            and not line.lstrip().startswith("#")
        ]
        assert offenders == [], (
            f"{module_path} re-inlines the raw validation filename instead of "
            f"resolving it from the Dataset Profile: {offenders}"
        )

    def test_the_parent_ships_one_profile_to_all_three(self):
        """One helper, three call sites — so the three children cannot be
        handed different declarations."""
        import core.sandbox_executor as sx

        source = inspect.getsource(sx)
        assert source.count("self._write_dataset_profile_config(exp_id)") == 3
        assert source.count('"--dataset_profile_json"') == 3
