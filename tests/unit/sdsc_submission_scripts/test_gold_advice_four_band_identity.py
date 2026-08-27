"""Gold campaign — the four bands are ONE treatment, and that is a CHECK.

The defect this module exists for, and why it is subtle. Hashing the advice
artifact inside ``gold_arm_args`` satisfies the letter of "all four Gold
bands use the same advice identity" and none of its substance:
``stage1_search.sh`` staggers four forks and each forked
``stage1_run_band.sh`` calls ``gold_arm_args`` ITSELF, so without an
inherited value each band observes the artifact at its own launch time,
declares its own digest, and its child certifies against that — trivially
equal, always. Four bands would run into four SEPARATE workspaces that no
per-workspace invariants lock can ever compare, an edit made during the
stagger window would go undetected, and every surface would report green.

A requirement satisfied by a mechanism that cannot fail is not satisfied.
The campaign entrypoint therefore observes the digest ONCE and threads it
down (``--gold_advice_sha256``, mirroring the F-PROFILE-WIRE-1 triple in the
same library), and each band compares its own read against that single
value. The comparison is what converts the tautology into a check.

What only these tests catch:

* ``TestTheCheck`` — the comparison itself. An artifact edited after the
  campaign bound it refuses the band BEFORE it launches.
* ``TestTheInheritanceIsThreaded`` — the regression that would silently
  restore the tautology: a stage script that stops passing the inherited
  value to ``gold_arm_args``, or that recomputes the digest locally. Every
  behavioural test below stays green through that edit, because a test
  fixture's artifact does not change between two calls in one process —
  which is exactly the property the production fleet does not have.
* ``TestTheFleetInherits`` — the plumbing, end to end through the real
  entrypoint: four bands, one digest, equal to one computed here.
* ``TestBlindpod`` — the control arm refuses a treated binding rather than
  ignoring it.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "sdsc_submission_scripts"
LIB = SCRIPTS / "_gold_campaign_lib.sh"
ENTRYPOINT = SCRIPTS / "run_gold_campaign.sh"

#: Every script that calls ``gold_arm_args`` on behalf of a band or stage and
#: must therefore hand it the campaign's inherited identity. The entrypoint is
#: deliberately absent: it is where the single observation is MADE.
INHERITING_CALLERS = (
    "stage1_search.sh",
    "stage1_run_band.sh",
    "stage2_strict_retrain.sh",
)


def _lib_call(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}" 2>/dev/null || true\n{body}\n'],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )


@pytest.fixture
def artifact(tmp_path: Path) -> tuple[Path, str]:
    p = tmp_path / "gold_advice.json"
    p.write_text('{"propose": "treatment as bound by the campaign"}\n')
    return p, hashlib.sha256(p.read_bytes()).hexdigest()


class TestTheCheck:
    def test_a_band_inheriting_the_same_identity_launches(self, artifact):
        """The normal path stays open. HOW THIS FAILS: compare something
        host-dependent and every legitimate band refuses."""
        path, sha = artifact
        out = _lib_call(f'gold_arm_args goldpod "{path}" "{sha}" && echo ACCEPTED')
        assert "ACCEPTED" in out.stdout, out.stderr

    def test_an_artifact_edited_after_the_campaign_bound_it_refuses_the_band(self, artifact):
        """THE defect. The campaign observes the artifact, the stagger window
        opens, someone edits the file, and band 15-19 launches.

        HOW THIS FAILS: delete the ``expected_sha`` comparison in
        ``gold_arm_args`` and this band launches a DIFFERENT treatment into a
        different workspace under the same arm label — with no downstream
        surface able to tell the two apart, because the bands' locks never
        meet."""
        path, campaign_sha = artifact
        path.write_text('{"propose": "EDITED during the stagger window"}\n')
        out = _lib_call(f'gold_arm_args goldpod "{path}" "{campaign_sha}"')
        assert out.returncode != 0
        assert "NOT the one this campaign bound" in out.stderr
        # Both digests are named, so the operator can tell WHICH file moved.
        assert campaign_sha in out.stderr
        assert hashlib.sha256(path.read_bytes()).hexdigest() in out.stderr

    def test_an_uninherited_call_still_binds_its_own_observation(self, artifact):
        """A directly-invoked band (or a hand run) has nothing to inherit; it
        must still DECLARE what it observed rather than declaring nothing.

        HOW THIS FAILS: make the emission conditional on an inherited value
        and a non-campaign launch silently loses its treatment pin."""
        path, sha = artifact
        out = _lib_call(f'gold_arm_args goldpod "{path}" && printf "%s " "${{GOLD_ARM_ARGS[@]}}"')
        assert out.returncode == 0, out.stderr
        assert f"--advice_sha256 {sha}" in out.stdout


class TestTheInheritanceIsThreaded:
    @pytest.mark.parametrize("script", INHERITING_CALLERS)
    def test_every_stage_caller_hands_gold_arm_args_the_inherited_identity(self, script):
        """The regression that silently restores the tautology.

        Drop the third argument at any of these sites and that stage's bands
        go back to observing the artifact independently. EVERY behavioural
        test in this file still passes, because a fixture's artifact does not
        change between two calls inside one process — and the production
        fleet's stagger window is precisely where it does.

        HOW THIS FAILS: the call reverts to two arguments, and this names the
        script."""
        src = (SCRIPTS / script).read_text(encoding="utf-8")
        calls = re.findall(r"gold_arm_args\s+([^\n|&;]*)", src)
        assert calls, f"{script}: no gold_arm_args call found"
        for call in calls:
            args = shlex.split(call.replace("||", " "))
            assert len(args) >= 3, (
                f"{script}: gold_arm_args is called with {len(args)} argument(s) "
                f"({call.strip()!r}); the THIRD is the campaign's inherited "
                f"advice identity. Without it this stage's bands observe the "
                f"artifact independently and the cross-band check becomes a "
                f"comparison of a value with itself."
            )

    @pytest.mark.parametrize("script", INHERITING_CALLERS)
    def test_no_stage_script_recomputes_the_digest(self, script):
        """Inherit, never re-observe. A stage that hashes the artifact itself
        reintroduces the independent observation by another route, and the
        argument census above would still pass.

        HOW THIS FAILS: a ``sha256sum`` appears in a stage script."""
        src = (SCRIPTS / script).read_text(encoding="utf-8")
        assert "sha256sum" not in src, (
            f"{script} computes a digest locally; the campaign entrypoint is "
            f"the ONE observer and every stage inherits its value."
        )

    def test_the_entrypoint_threads_it_to_both_stages(self):
        """``run_gold_campaign.sh`` is where the single observation is made
        and must hand it to whatever it dispatches.

        HOW THIS FAILS: compute it for the manifest but forget the COMMON
        thread — the manifest would then report an identity no band was ever
        told about, which is the failure mode the reserved-passthrough note
        calls "a pin the manifest misreports"."""
        src = ENTRYPOINT.read_text(encoding="utf-8")
        assert "COMMON+=(--gold_advice_sha256" in src
        # The manifest keys are emitted from inside a double-quoted `echo`,
        # so the source carries them backslash-escaped.
        assert r"\"advice_sha256\"" in src, "the launch manifest must record the bound identity"
        assert r"\"advice_path\"" in src, "the launch manifest must record the bound artifact"

    def test_the_chain_level_spelling_is_reserved(self):
        """``_chain_common.sh``'s parse loop is last-wins and passthrough
        tokens are appended AFTER the frozen args, so a passed-through
        ``--advice_sha256`` would rebind the identity the manifest reports.

        HOW THIS FAILS: drop it from ``GOLD_RESERVED_PASSTHROUGH`` and an
        operator can silently redeclare the campaign's treatment."""
        out = _lib_call("gold_refuse_reserved_passthrough --advice_sha256")
        assert out.returncode != 0
        assert "--advice_sha256" in out.stderr


class TestTheBandRefusesAfterAnEdit:
    def test_an_edit_between_launch_and_band_spawn_refuses_that_band(self, tmp_path):
        """The operator's scenario, end to end through the REAL band script.

        The campaign observes the artifact and forks; the stagger window
        opens; someone edits the file; band 15-19 spawns. It must refuse.

        Only the CAMPAIGN side of the digest is constructed here — that is
        the captured pin the entrypoint transports. Everything after it is
        production: ``stage1_run_band.sh`` parses ``--gold_advice_sha256``,
        hands it to ``gold_arm_args``, which reads the artifact itself and
        compares. HOW THIS FAILS: any hop that drops the value, or a
        comparison downgraded to a warning, and the band launches a second
        treatment into its own workspace under the first one's arm label."""
        genlib = tmp_path / "genlib"
        genlib.mkdir()
        root = tmp_path / "ws"
        root.mkdir()
        advice = tmp_path / "advice.json"
        advice.write_text('{"propose": "as bound at launch"}\n')
        campaign_sha = hashlib.sha256(advice.read_bytes()).hexdigest()

        advice.write_text('{"propose": "EDITED during the stagger window"}\n')

        env = dict(os.environ)
        env.pop("CUDA_VISIBLE_DEVICES", None)
        env["SIDERIUS_GENERATED_LIBRARY_DIR"] = str(genlib)
        proc = subprocess.run(
            [
                "bash",
                str(SCRIPTS / "stage1_run_band.sh"),
                "--band",
                "15-19",
                "--workspace_root",
                str(root),
                "--arm",
                "goldpod",
                "--gold_advice_file",
                str(advice),
                "--gold_advice_sha256",
                campaign_sha,
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=300,
        )
        assert proc.returncode != 0, "band 15-19 launched with a treatment the campaign never bound"
        assert "NOT the one this campaign bound" in proc.stderr
        assert campaign_sha in proc.stderr


class TestTheFleetInherits:
    def test_all_four_bands_receive_the_campaigns_one_identity(self, tmp_path):
        """The plumbing, end to end through the real entrypoint's dry run.

        HOW THIS FAILS: any hop that drops the token — the entrypoint's
        COMMON, ``stage1_search.sh``'s parse or its BAND_ARGS_COMMON,
        ``stage1_run_band.sh``'s parse — and the count of bands carrying the
        digest stops being four."""
        root = tmp_path / "ws"
        root.mkdir()
        genlib = tmp_path / "genlib"
        genlib.mkdir()
        advice = tmp_path / "advice.json"
        advice.write_text('{"propose": "placeholder"}\n')
        expected = hashlib.sha256(advice.read_bytes()).hexdigest()

        env = dict(os.environ)
        env.pop("CUDA_VISIBLE_DEVICES", None)
        env["SIDERIUS_GENERATED_LIBRARY_DIR"] = str(genlib)
        proc = subprocess.run(
            [
                "bash",
                str(ENTRYPOINT),
                "--workspace_root",
                str(root),
                "--stage",
                "1",
                "--gold_advice_file",
                str(advice),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=300,
        )
        assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
        bands = [ln for ln in proc.stdout.splitlines() if "run_chain argv:" in ln]
        assert len(bands) == 4, f"expected four bands, saw {len(bands)}"
        seen = re.findall(r"--advice_sha256 ([0-9a-f]{64})", proc.stdout)
        assert len(seen) == 4, f"only {len(seen)} band(s) carry the identity"
        assert set(seen) == {expected}, (
            f"the four bands do not share the campaign's identity: {sorted(set(seen))} "
            f"vs expected {expected}"
        )


class TestBlindpod:
    def test_the_control_arm_refuses_an_inherited_identity(self, artifact):
        """blindpod is the WITHOUT_ADVICE arm and consumes no artifact, so a
        digest reaching it means the control arm was launched from a treated
        binding.

        HOW THIS FAILS: ignore the third argument for blindpod and the
        contradiction passes silently — the same class as the lock's own
        stored-side-conditional hazard, where the control arm quietly
        acquires the treatment."""
        _path, sha = artifact
        out = _lib_call(f'gold_arm_args blindpod "" "{sha}"')
        assert out.returncode != 0
        assert "blindpod refuses an inherited advice identity" in out.stderr

    def test_an_untreated_blindpod_launch_carries_no_digest(self, artifact):
        """The differential: blindpod's argv gains nothing."""
        out = _lib_call('gold_arm_args blindpod "" && printf "%s " "${GOLD_ARM_ARGS[@]}"')
        assert out.returncode == 0, out.stderr
        assert "--advice" not in out.stdout
