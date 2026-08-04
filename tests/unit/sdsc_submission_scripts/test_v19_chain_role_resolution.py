"""A chain's role comes from the ROSTER, never from its name.

V20 launch blocker, found during the PR E audit and fixed ahead of it.

The wave path used to recover a chain's role by stripping a literal prefix:

    FLAVOR="arch"; [ "${RUN#v19_loss_}" != "$RUN" ] && FLAVOR="loss"

Run names are built from ``${CAMPAIGN_ID}`` (the ROSTER at
``v19_queue_runner.sh:124-131``), so under any campaign id other than
``v19`` the loss chain did not match, fell through to ``arch``, and BOTH
chains of every wave launched with ``advice/workflow/v18r_arch_explorer.json``
(``:271``). The queue still showed two chains, so the pair looked correct
while both arms ran the same treatment — a difference that would surface
only at analysis time. **V20 launches with a new campaign id by
definition**, so it would have hit this on wave 1.

The fix is deliberately NOT ``s/v19_/v20_/``: that defers the identical
defect to V21. The implicit name-encodes-role protocol is deleted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"


def _role_for(run: str, campaign_id: str = "v19") -> subprocess.CompletedProcess[str]:
    """Source the runner's declarations and ask it for one run's role.

    Sources only as far as the helper needs: the ROSTER and
    ``role_for_run``. The runner guards its own main loop behind an
    execution check, so sourcing does not launch anything.
    """
    script = f"""
    set -euo pipefail
    export CAMPAIGN_ID={campaign_id!r}
    # Extract just the declarations under test, so sourcing cannot run the queue.
    eval "$(sed -n '/^ROSTER=(/,/^)/p' {str(RUNNER)!r})"
    eval "$(sed -n '/^role_for_run()/,/^}}/p' {str(RUNNER)!r})"
    role_for_run {run!r}
    """
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)


class TestTheRoleComesFromTheRoster:
    @pytest.mark.parametrize(
        ("campaign_id", "band"),
        [("v19", "15_19"), ("v20", "15_19"), ("v21_pilot", "04_09"), ("x", "00_03")],
    )
    def test_both_roles_resolve_under_any_campaign_id(self, campaign_id, band):
        """THE REGRESSION. Under the old rule every non-``v19`` campaign
        resolved the loss chain to ``arch``."""
        arch = _role_for(f"{campaign_id}_arch_{band}", campaign_id)
        loss = _role_for(f"{campaign_id}_loss_{band}", campaign_id)
        assert arch.returncode == 0, arch.stderr
        assert loss.returncode == 0, loss.stderr
        assert arch.stdout.strip() == "arch"
        assert loss.stdout.strip() == "loss", (
            f"campaign {campaign_id!r} resolved its loss chain to "
            f"{loss.stdout.strip()!r} — the launch blocker is back"
        )

    def test_v19_behaviour_is_unchanged(self):
        """The existing campaign must resolve exactly as before the fix."""
        for band in ("15_19", "10_14", "04_09", "00_03"):
            assert _role_for(f"v19_arch_{band}").stdout.strip() == "arch"
            assert _role_for(f"v19_loss_{band}").stdout.strip() == "loss"

    def test_the_two_roles_are_distinct_for_every_wave(self):
        """A wave whose two chains resolve to the same role is not a
        controlled pair, whatever the queue displays."""
        for campaign_id in ("v19", "v20", "v21_pilot"):
            for band in ("15_19", "10_14", "04_09", "00_03"):
                a = _role_for(f"{campaign_id}_arch_{band}", campaign_id).stdout.strip()
                b = _role_for(f"{campaign_id}_loss_{band}", campaign_id).stdout.strip()
                assert a != b, f"{campaign_id} wave {band}: both chains resolved to {a!r}"

    def test_the_roles_select_different_advice_configs(self):
        """The role's only consumer is the advice path at `:271`. Distinct
        roles must therefore mean distinct configs — that is the whole
        reason the defect mattered."""
        text = RUNNER.read_text(encoding="utf-8")
        assert "advice/workflow/v18r_${FLAVOR}_explorer.json" in text
        for campaign_id in ("v19", "v20"):
            a = _role_for(f"{campaign_id}_arch_15_19", campaign_id).stdout.strip()
            b = _role_for(f"{campaign_id}_loss_15_19", campaign_id).stdout.strip()
            assert f"v18r_{a}_explorer.json" != f"v18r_{b}_explorer.json", (
                f"{campaign_id}: both chains would load v18r_{a}_explorer.json"
            )


class TestItFailsClosed:
    def test_an_unknown_run_fails_rather_than_defaulting(self):
        """MUTATION TARGET: restoring a default.

        Defaulting to ``arch`` is exactly how the original defect stayed
        invisible for a whole campaign.
        """
        r = _role_for("v19_nonsense_15_19")
        assert r.returncode != 0
        assert r.stdout.strip() != "arch"
        assert "no roster entry" in r.stderr

    def test_an_empty_role_fails(self):
        """A roster entry with an empty fourth field is a malformed
        declaration, not an instruction to guess."""
        script = f"""
        set -euo pipefail
        ROSTER=("broken_run:15-19:15,16:")
        eval "$(sed -n '/^role_for_run()/,/^}}/p' {str(RUNNER)!r})"
        role_for_run 'broken_run'
        """
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        assert r.returncode != 0
        assert "empty role" in r.stderr

    def test_the_wave_path_stops_instead_of_launching_on_an_unresolvable_role(self):
        """Structural: the wave loop must refuse the launch, not proceed."""
        text = RUNNER.read_text(encoding="utf-8")
        assert 'if ! FLAVOR="$(role_for_run "$RUN")"; then' in text
        block = text[text.index('if ! FLAVOR="$(role_for_run') :]
        block = block[: block.index("if launch_chain")]
        assert "record_queue_stop" in block
        assert "exit" in block


class TestTheImplicitProtocolIsDeleted:
    def test_no_live_code_derives_a_role_from_a_run_name(self):
        """MUTATION TARGET: reinstating the prefix strip, in any campaign's
        spelling. `s/v19_/v20_/` is not a fix — it defers the same defect."""
        offenders = []
        for line in RUNNER.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # the fix's own explanation quotes the old line
            if "_loss_}" in stripped or "_arch_}" in stripped:
                offenders.append(stripped)
        assert not offenders, f"a chain role is being derived from the run name again: {offenders}"

    def test_the_only_path_still_reads_the_roster_directly(self):
        """`--only` was never affected — it already read field 4 — and must
        keep doing so."""
        text = RUNNER.read_text(encoding="utf-8")
        assert 'IFS=: read -r RUN SCOPE FILES FLAVOR <<< "$spec"' in text

    def test_launch_chain_still_takes_the_role_as_its_fourth_argument(self):
        """Both paths must reach one launch contract."""
        text = RUNNER.read_text(encoding="utf-8")
        assert 'local RUN="$1" SCOPE="$2" FILES="$3" FLAVOR="$4"' in text
        assert text.count('launch_chain "$RUN" "$SCOPE" "$FILES" "$FLAVOR"') == 2
