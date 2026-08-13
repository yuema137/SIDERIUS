"""PR-02b B1 — the SampleSet JSON round-trip contract, captured BEFORE change.

`SampleSet = dict[int, list[int]]` is produced with **integer** keys, crosses
exactly two production `json.dump` boundaries in `core/sandbox_executor.py`
(train `:1307`, eval `:1639`), and arrives at the subprocess with **string**
keys, because that is what JSON is. Consumers then re-int independently.

This module pins that LIVE transport contract at the real production
boundary, before PR-02b touches selection. Capture-after-edit would pin
already-changed behaviour and prove nothing.

Failure class guarded (design §8): **round-trip / key-coercion drift** — the
transport shape changing silently. The five sha16 selection digests cannot
catch it: they hash ``json.dumps(ss, sort_keys=True)``, and
``json.dumps({0: [1]})`` and ``json.dumps({"0": [1]})`` are the same bytes.
The digests are structurally blind to producer key type, which is precisely
why this module exists alongside them rather than duplicating them.

Deliberately NOT re-pinned here (already covered, no duplication):
`validate_sample_set`'s string-key coercion, scope violations and
out-of-range rejection are pinned by
`tests/unit/core/test_sandbox_scope.py::TestValidateSampleSetScope`. Only the
two negative cases that module does not cover — an empty SampleSet and a
non-integer-like key — are added below, per design §6.1's validation plan.

LATENT finding — recorded, deliberately NOT frozen
--------------------------------------------------
Two consumers re-int post-JSON keys differently:

    TIDMADDataset._pull_events_from_sample_set   sorted(sample_set.items())
    TIDMADEpochDataset.__init__                  sorted(keys, key=int)

Only the second runs in production. Source audit at base ``dc26bb75``: every
production ``TIDMADDataset(...)`` construction uses the ``fname_list`` branch
and passes no ``sample_set=`` — ``train_engine_sandbox.py:1351`` (legacy
single-file) and ``probe_data.py:29`` (VRAM probe). The live multi-file path
constructs ``TIDMADEpochDataset`` (``train_engine_sandbox.py:884-891``).

So the first consumer's ordering is **production-unreachable**, and this
module asserts **nothing** about it. Freezing an unreachable branch's output
would promote a latent bug into a compatibility promise nobody could later
change — the opposite of what a capture-first baseline is for. PR-02b does
not fix it either (operator decision Q2). If it ever becomes reachable, that
is a production defect and a different PR.
"""

import json
import os
from unittest.mock import patch

import pytest

from core.sandbox_executor import TidmadSandbox
from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.scoring_utils import validate_sample_set
from execute_tools.train_engine_sandbox import TIDMADEpochDataset

# Mirrors tests/unit/core/test_sandbox_scope.py — minimal configs that pass
# Pydantic validation without a GPU or real data.
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
EXP_ID = "b1_roundtrip_exp"
RUN_NAME = "b1_roundtrip"

# File indices chosen so numeric and lexicographic key order DISAGREE:
#   numeric        -> 4, 9, 12
#   lexicographic  -> "12", "4", "9"
# A test that cannot tell the two apart would pass for the wrong reason.
DIVERGENT_SS = {4: [0, 1], 9: [5], 12: [2, 3]}


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path))


def _argv_from(*mocks) -> list[str]:
    """The argv handed to whichever launch primitive the executor used.

    All three primitives are patched by the callers below, so this never
    goes vacuously true by the executor being rewired past one seam — the
    failure mode that nearly lost the DS3 coverage in the B-C2a migration.
    """
    for mock in mocks:
        if mock.called:
            return mock.call_args[0][0]
    raise AssertionError("no subprocess launch primitive was called")


def _sample_set_json_path(sandbox, phase: str, sample_set: dict) -> str:
    """Drive the REAL production boundary and return the file it wrote.

    The path comes from ``--sample_set_json`` in the actual argv, never from
    the filename convention: reading by convention would still pass if the
    executor stopped passing the flag at all.
    """
    with (
        patch("core.sandbox_executor._run_observed_subprocess") as m_obs,
        patch("core.sandbox_executor.subprocess.run") as m_run,
        patch("core.sandbox_executor.subprocess.Popen") as m_popen,
    ):
        m_obs.return_value = (type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(), None)
        try:
            if phase == "train":
                sandbox.execute_training(
                    EXP_ID,
                    RUN_NAME,
                    "fcnet",
                    MODEL_CFG,
                    TRAIN_CFG,
                    LOSS_CFG,
                    sample_set=sample_set,
                )
            else:
                sandbox.execute_inference(
                    EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG, sample_set=sample_set
                )
        except Exception:
            # The mocked launch returns no usable result. Only the argv and
            # the file written before launch are under test here.
            pass
        cmd = _argv_from(m_obs, m_run, m_popen)

    assert "--sample_set_json" in cmd, f"{phase} site stopped passing --sample_set_json"
    path = cmd[cmd.index("--sample_set_json") + 1]
    assert os.path.isfile(path), f"{phase} site did not write {path}"
    return path


# ---------------------------------------------------------------------------
# 1. Producer side — integer keys
# ---------------------------------------------------------------------------


class TestProducerEmitsIntegerKeys:
    """The digests cannot see this: JSON stringifies both int and str keys."""

    def test_trial_sample_set_keys_are_int(self):
        ss = build_sample_set(is_trial=True, trial_strategy="snapshot", trial_portion=0.05, seed=42)
        assert ss, "builder returned an empty SampleSet"
        assert all(type(k) is int for k in ss), (
            f"non-int keys: {[k for k in ss if type(k) is not int]}"
        )

    def test_normal_mode_sample_set_keys_are_int(self):
        ss = build_sample_set(is_trial=False, file_index=6)
        assert all(type(k) is int for k in ss)


# ---------------------------------------------------------------------------
# 2-3. The two production boundaries — string keys out, values unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phase", ["train", "eval"])
class TestProductionBoundaryRoundTrip:
    """Both `json.dump(sample_set, f)` sites, driven through the real
    executor methods rather than a re-implemented `json.dump`."""

    def test_boundary_emits_string_keys(self, sandbox, phase):
        path = _sample_set_json_path(sandbox, phase, DIVERGENT_SS)
        with open(path) as f:
            loaded = json.load(f)
        assert all(type(k) is str for k in loaded), (
            f"{phase} boundary emitted non-string keys {list(loaded)} — the JSON "
            "transport contract changed"
        )
        assert set(loaded) == {str(k) for k in DIVERGENT_SS}

    def test_boundary_preserves_value_lists_exactly(self, sandbox, phase):
        path = _sample_set_json_path(sandbox, phase, DIVERGENT_SS)
        with open(path) as f:
            loaded = json.load(f)
        for file_index, segments in DIVERGENT_SS.items():
            assert loaded[str(file_index)] == segments, (
                f"{phase} boundary altered the segment list for file {file_index}"
            )

    def test_boundary_rejects_an_invalid_sample_set_before_launch(self, sandbox, phase):
        """The validator hop is REACHABLE at both sites.

        Deliberately not "the file equals validate_sample_set(raw)": the
        validator returns its segment lists untouched and only re-keys, and
        `json.dump` stringifies keys either way — so that comparison holds
        whether or not the validator ever ran, and would survive deleting
        the hop. Rejection is the validator's only observable effect here.

        Distinct from `test_sandbox_scope.py`, which covers SCOPE violations;
        this covers the plain out-of-range path.

        The two sites reject with DIFFERENT outward shapes, pinned here as
        measured, not as assumed. `execute_training` wraps its body in a
        broad `except Exception` (`sandbox_executor.py:1511-1512`) and
        converts the error into a status dict; `execute_inference` catches
        only `ScopeViolationError` (`:1628`), so a plain `ValueError`
        propagates. That asymmetry is PRE-EXISTING and PR-02b must not
        "tidy" it — the invariant both share is rejection before any launch.
        """
        out_of_range = {999: [0]}
        with (
            patch("core.sandbox_executor._run_observed_subprocess") as m_obs,
            patch("core.sandbox_executor.subprocess.run") as m_run,
            patch("core.sandbox_executor.subprocess.Popen") as m_popen,
        ):
            if phase == "train":
                result = sandbox.execute_training(
                    EXP_ID,
                    RUN_NAME,
                    "fcnet",
                    MODEL_CFG,
                    TRAIN_CFG,
                    LOSS_CFG,
                    sample_set=out_of_range,
                )
                assert result["status"] == "error"
                assert "out of range" in result["message"]
            else:
                with pytest.raises(ValueError, match="out of range"):
                    sandbox.execute_inference(
                        EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG, sample_set=out_of_range
                    )
            m_obs.assert_not_called()
            m_run.assert_not_called()
            m_popen.assert_not_called()


# ---------------------------------------------------------------------------
# 4. The LIVE consumer re-ints NUMERICALLY
# ---------------------------------------------------------------------------


class TestLiveConsumerReintsNumerically:
    """`TIDMADEpochDataset` is the consumer the production training path
    constructs. Its visited file order must stay numeric.

    Observed through the real constructor against an absent data dir: the
    loop at `train_engine_sandbox.py:333-338` iterates in its coercion order
    and prints a skip warning per file, so the visited sequence is
    observable without any HDF5 fixture. The constructor then yields empty
    arrays rather than raising (`:375-384`).
    """

    def _visited(self, capsys, sample_set, tmp_path) -> list[int]:
        TIDMADEpochDataset(data_dir=str(tmp_path / "absent"), sample_set=sample_set, seg_size=10000)
        out = capsys.readouterr().out

        # Map the profile's own filenames back to indices rather than
        # scraping digits out of the warning text: ".h5" carries a digit of
        # its own, so a digit-scrape reads file 4 as 45 and the order
        # assertion would compare nonsense.
        dataset = resolve_dataset_profile().dataset
        by_name = {dataset.training_file_name(int(k)): int(k) for k in sample_set}

        visited = []
        for line in out.splitlines():
            if "not found" not in line:
                continue
            for name, index in by_name.items():
                if name in line:
                    visited.append(index)
                    break
        return visited

    def test_visited_order_is_numeric_after_the_json_round_trip(self, capsys, tmp_path):
        post_json = {str(k): v for k, v in DIVERGENT_SS.items()}
        visited = self._visited(capsys, post_json, tmp_path)

        assert visited == sorted(DIVERGENT_SS), (
            f"live consumer visited {visited}; the production contract is numeric "
            f"key coercion, i.e. {sorted(DIVERGENT_SS)}"
        )
        # Computed, never hardcoded: this states "not the string ordering"
        # without enshrining the latent branch's output as an expectation.
        lexicographic = [int(k) for k in sorted(post_json)]
        assert visited != lexicographic, (
            "the live consumer fell back to lexicographic key ordering — the "
            "latent divergence has become live, which is a production defect "
            "and a different PR (design §6.1 stop condition)"
        )


# ---------------------------------------------------------------------------
# 5. Negative cases the existing scope module does not cover
# ---------------------------------------------------------------------------


class TestBoundaryValidatorNegativeCases:
    """Pins today's behaviour, whatever it is (design §6.1)."""

    def test_empty_sample_set_is_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_sample_set({})

    def test_non_integer_like_key_is_rejected(self):
        with pytest.raises(ValueError, match="key must be an integer"):
            validate_sample_set({"file_seven": [0]})
