"""PR-05a CHECKPOINT A — historical configuration replays without migration.

Design `step_05a_tuner_data_selection.md` §6.1 and §17 CHECKPOINT A require
that *a representative historical TIDMAD serialized configuration loads under
post-05a code WITHOUT migration and resolves to the same effective
model / loss / train / tuner semantics.*

Deliberately narrow. The other Checkpoint-A surfaces already have oracles and
are NOT restated here:

* `TrialConfig` serialized form deep-equal — `test_step00_record_baselines.py`
  `TestTC1bOnDiskTrialConfigArtifact`, which compares a fresh tuner run's
  on-disk artifacts against a committed golden;
* schema field lists — the same module's `TestREC1FieldLists`;
* SampleSet identities — `test_formal_sample_set.py` and the Step-02b
  modules;
* legality verdict + exact diagnostic, and legacy `single_file` counts —
  `test_step05a_checkpoint0_baselines.py`.

What none of those covers is the **reading** direction. TC1b proves the form
this code PRODUCES has not moved; it does not prove that a document written
by an older build still LOADS. A migration that quietly made a field required
would keep TC1b green (fresh runs supply it) while breaking every stored
config — which is exactly the failure §6.1 forbids.

The two artifacts used are genuinely historical: both were committed before
05a existed, and neither is a fixture authored for this test.
"""

import json
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import TrialConfig

REPO_ROOT = Path(__file__).resolve().parents[4]
GOLDENS = Path(__file__).resolve().parent / "goldens"

# Written by a pre-05a tuner run and committed as a Step-00 golden.
HISTORICAL_TRIAL_CONFIGS = GOLDENS / "tc1b_on_disk_trial_configs.json"


def _historical_trial_configs() -> list[tuple[str, dict]]:
    payload = json.loads(HISTORICAL_TRIAL_CONFIGS.read_text())
    return [(entry["file"], entry["config"]) for entry in payload]


class TestHistoricalTunerConfigReplay:
    @pytest.mark.parametrize("name,stored", _historical_trial_configs())
    def test_a_stored_trial_config_loads_and_round_trips_unchanged(self, name, stored):
        """Loads with no migration step, and dumps back byte-for-byte.

        Both halves matter. Loading alone would pass if a field had acquired
        a new default that silently rewrote the value; the deep-equal dump is
        what proves the *effective* tuner semantics are the stored ones.
        """
        resolved = TrialConfig.model_validate(stored)
        assert resolved.model_dump() == stored, (
            f"{name} did not round-trip: the stored configuration no longer "
            "resolves to the same effective tuner semantics"
        )

    def test_the_historical_corpus_is_not_empty(self):
        """A parametrized suite over an empty list is vacuously green."""
        configs = _historical_trial_configs()
        assert len(configs) == 3, (
            f"expected the committed Step-00 golden's 3 configs, got {len(configs)}"
        )
