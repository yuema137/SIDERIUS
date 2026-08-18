"""Step 07 PR 07b — the example packs' 07b maturity claims are true.

Design: ``docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/
pr_07b_tuner_policy.md`` §3.12 / C6.

A STATUS row is a promise to a reader about what the framework can actually do
with a pack. The defect these pins catch is the one that makes an example pack
worthless: a row claiming a maturity the code does not deliver — or, just as
bad, a row claiming REAL execution where only a declaration was consumed.

So each claim is checked against the thing it claims about:

* TIDMAD says *production-backed* — and the order authority really is
  constructed from this pack's declared direction, in production.
* Pets and DAVIS say *L1, declaration-backed, no executable path* — so the
  test asserts their declared specs are consumed AND that the packs still
  carry no executable path (the PR0 maturity pins, which D14 owns).

No new fixture files: the rungs and these pins read the packs' OWN
``declared/`` and ``expected/`` files, so a pack cannot drift from its claim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.examples import maturity_vocabulary as mv

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"


def _status(pack: str) -> str:
    return (EXAMPLES / pack / "STATUS.md").read_text(encoding="utf-8")


class TestTidmadClaimsProductionBacking:
    def test_the_status_row_claims_production_backing_from_07b(self):
        row = _status("tidmad")
        assert "metric-direction policy / planner-reflector rendering" in row
        assert mv.MATURITY_PRODUCTION_07B in row

    def test_and_the_claim_is_true_at_the_production_seam(self):
        """The row is only honest if the shipped run really derives its order
        from this pack's declaration. Constructed here the way the tuner does."""
        from execute_tools.dataset_config import TIDMAD_PROFILE
        from execute_tools.evaluation_metric import derive_tidmad_metric_spec
        from execute_tools.metric_order import MetricOrder

        spec = derive_tidmad_metric_spec(TIDMAD_PROFILE)
        order = MetricOrder(spec)
        assert order.direction == spec.direction == "higher"
        assert order.is_better(-2.55, -2.91)

    def test_the_readme_points_at_the_order_authority(self):
        readme = (EXAMPLES / "tidmad" / "README.md").read_text(encoding="utf-8")
        assert "execute_tools/metric_order.py" in readme


@pytest.mark.parametrize(
    ("pack", "metric_file", "metric_id", "direction"),
    [
        ("oxford_iiit_pet", "metric_accuracy.json", "accuracy", "higher"),
        ("davis_future_prediction", "metric_mse.json", "mse", "lower"),
    ],
    ids=["pets", "davis"],
)
class TestContrastPacksClaimL1Only:
    def test_the_status_row_claims_L1_and_names_the_rungs(
        self, pack, metric_file, metric_id, direction
    ):
        row = _status(pack)
        assert mv.MATURITY_L1_DECLARATION in row
        assert all(r in row for r in mv.RUNGS_07B), f"the row must name {mv.RUNGS_07B}"
        assert f"`{metric_id}`" in row and f"`{direction}`-is-better" in row

    def test_the_row_does_not_claim_real_execution(self, pack, metric_file, metric_id, direction):
        """The failure this catches is a pack quietly upgrading its own claim.
        D14 owns real Pets/DAVIS execution; until then the row must say so."""
        row = _status(pack)
        assert "no real" in row.lower() or "no executable path" in row
        assert mv.DEFERRAL_TOKEN in row

    def test_the_declared_spec_the_row_points_at_actually_declares_that(
        self, pack, metric_file, metric_id, direction
    ):
        declared = json.loads(
            (EXAMPLES / pack / "declared" / metric_file).read_text(encoding="utf-8")
        )
        assert declared["id"] == metric_id
        assert declared["direction"] == direction

    def test_the_declared_direction_drives_the_order_authority_unchanged(
        self, pack, metric_file, metric_id, direction
    ):
        """L1 means the DECLARATION is consumed by production code without a
        pack-specific branch — which is the claim, and the only one made."""
        from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
        from execute_tools.metric_order import MetricOrder

        declared = json.loads(
            (EXAMPLES / pack / "declared" / metric_file).read_text(encoding="utf-8")
        )
        order = MetricOrder(
            MetricSpec(
                id=declared["id"],
                direction=declared["direction"],
                aggregation=declared["aggregation"],
                scoreability=PresenceScoreabilityContract(),
            )
        )
        assert order.direction == direction
        # 0.9 beats 0.1 on accuracy; 0.1 beats 0.9 on mse.
        assert order.is_better(0.9, 0.1) is (direction == "higher")

    def test_any_pack_python_is_sanctioned_plugin_source_only(
        self, pack, metric_file, metric_id, direction
    ):
        """The PR0 maturity pin, RE-SCOPED BY D14-2 (the named relaxation
        owner — see `test_pack_governance` guard (b)): the only ``.py`` a
        pack may ship is reference PLUGIN SOURCE at
        ``examples/<pack>/plugins/*.py`` (loaded dynamically, never
        imported). Anything else under a pack is still an executable path
        hiding where the maturity claims forbid one."""
        offenders = [
            p
            for p in (EXAMPLES / pack).rglob("*.py")
            if p.parent.name != "plugins" or p.parent.parent != EXAMPLES / pack
        ]
        assert offenders == []
