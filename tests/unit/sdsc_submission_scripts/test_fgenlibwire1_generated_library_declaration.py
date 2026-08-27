"""F-GENLIB-WIRE-1 — the generated-capability library root must be DECLARED.

`core/generated_library.py` has resolved the library root from
``SIDERIUS_GENERATED_LIBRARY_DIR`` since arXiv P1, and falls back to
``~/.siderius/generated_library`` when the variable is unset. Nothing in the
repository ever set it: the whole `SIDERIUS_*` export census found only
tests. So every campaign resolved the DEFAULT root — which on a pod is the
ephemeral container overlay AND is shared across campaigns, so promoted
models and losses from one arm become visible to the next arm's proposer,
and the run still exits 0.

The repair is split by responsibility, and neither half alone is enough:

* the **Gold launcher** requires the variable to be SET, refusing to launch
  when it is not. It does NOT dictate the value — nothing machine-specific
  enters tracked code. This is what puts the requirement ON the launch path
  by construction, which a preflight-only guard cannot do because preflight
  is a separate invocation an operator can skip.
* **`campaign_preflight.sh` R1c** validates the PROPERTIES of whatever was
  supplied, resolving it by CALLING the production authority rather than
  re-deriving it, and failing on a default or ephemeral root.

So: the launcher requires the operator to have made the decision; preflight
validates that the decision is sound.

**These tests deliberately never assert through R8.** R8 globs the CHECKOUT
directory only and is structurally blind to this root — which is exactly how
the contamination went unseen. The assertions here are against the
production resolution authority (`generated_library_provenance`, whose
output the run-invariants lock stores verbatim at
`core/run_invariants.py:745`) and against the launcher's own observable
surfaces.

The authority's own semantics, and the lock field, are owned by
``tests/unit/core/test_generated_library.py`` and are not restated here.
What this file owns is the LINK: that the thing the launcher demands is the
thing production actually reads.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from core.generated_library import (
    GENERATED_LIBRARY_ENV_VAR,
    generated_library_provenance,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SDSC = REPO_ROOT / "sdsc_submission_scripts"
ENTRYPOINT = SDSC / "run_gold_campaign.sh"
STAGE1_BAND = SDSC / "stage1_run_band.sh"
STAGE2 = SDSC / "stage2_strict_retrain.sh"
PREFLIGHT = SDSC / "campaign_preflight.sh"

#: The four properties the refusal must state. HARDCODED: reading them back
#: out of the script would compare the message to itself.
REQUIRED_PROPERTIES = ("ABSOLUTE", "PERSISTENT", "CAMPAIGN-OWNED", "FRESH")


def _bash(*argv: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a campaign script with a controlled environment.

    ``SIDERIUS_GENERATED_LIBRARY_DIR`` is REMOVED by default: the pytest
    session sets it (``tests/conftest.py`` isolation fixture), and inheriting
    that would make the undeclared case untestable — the very state these
    tests exist to reject would silently look declared.
    """
    merged = dict(os.environ)
    merged.pop("CUDA_VISIBLE_DEVICES", None)
    merged.pop(GENERATED_LIBRARY_ENV_VAR, None)
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", *argv],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=merged,
        timeout=300,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def advice(tmp_path: Path) -> Path:
    path = tmp_path / "advice.json"
    path.write_text('{"propose": "placeholder"}\n')
    return path


def _stage1_dry(workspace: Path, advice: Path, **env: str) -> subprocess.CompletedProcess:
    return _bash(
        str(ENTRYPOINT),
        "--workspace_root",
        str(workspace),
        "--stage",
        "1",
        "--gold_advice_file",
        str(advice),
        "--dry-run",
        "--only",
        "0-3",
        env=dict(env) or None,
    )


class TestGoldLauncherRequiresTheDeclaration:
    def test_an_undeclared_launch_is_refused_naming_the_variable(self, workspace, advice):
        """The defect only this catches: the launcher accepting a campaign
        that never declared where promoted capabilities go. That run does not
        fail — it silently writes into the shared default root, so the next
        arm's proposer sees the previous arm's promoted models and the arms
        stop being isolated.

        Fails by: exit 0, or a refusal that does not name the variable, or
        one that does not state what the operator must supply."""
        proc = _stage1_dry(workspace, advice)
        assert proc.returncode != 0, proc.stdout
        assert GENERATED_LIBRARY_ENV_VAR in proc.stderr
        for prop in REQUIRED_PROPERTIES:
            assert prop in proc.stderr, f"the refusal must state {prop}: {proc.stderr}"

    def test_the_refusal_does_not_suggest_a_value(self, workspace, advice):
        """The defect only this catches: a refusal that helpfully proposes a
        path. The correct root is a property of the machine and of WHICH
        campaign this is; a suggested value would be copy-pasted, and a
        campaign-owned FRESH directory cannot be guessed by tracked code.

        Fails by: the message containing an absolute path that reads as a
        recommendation."""
        proc = _stage1_dry(workspace, advice)
        assert proc.returncode != 0
        suggestion_shapes = (
            "/mnt/",
            "/persist",
            "/workspace/",
            "export SIDERIUS_GENERATED_LIBRARY_DIR=",
        )
        for shape in suggestion_shapes:
            assert shape not in proc.stderr, (
                f"the refusal must not suggest a value; found {shape!r}"
            )

    def test_a_declared_launch_is_accepted_and_names_the_supplied_root(
        self, workspace, advice, tmp_path
    ):
        """The defect only this catches: a requirement that refuses
        everything (making the campaign unlaunchable), or one that accepts
        without recording WHICH root was bound — leaving the operator unable
        to confirm from the dry run where capabilities will land.

        Fails by: a non-zero exit with the variable set, or the supplied root
        missing from the printed row."""
        lib = tmp_path / "campaign_library"
        lib.mkdir()
        proc = _stage1_dry(workspace, advice, **{GENERATED_LIBRARY_ENV_VAR: str(lib)})
        assert proc.returncode == 0, proc.stderr + proc.stdout
        rows = [line for line in proc.stdout.splitlines() if "supplied generated_library=" in line]
        assert rows, proc.stdout
        assert all(str(lib) in row for row in rows), rows

    def test_every_stage_enforces_it_not_only_the_entrypoint(self, workspace, tmp_path):
        """The defect only this catches: enforcement at the entrypoint alone.
        The stage scripts are separately executable — a resumed or manually
        re-driven stage would bypass an entrypoint-only check and land in the
        shared default root, which is precisely the state being fixed.

        Fails by: either stage script accepting an undeclared launch."""
        registry = tmp_path / "designs"
        registry.mkdir()
        for design in ("wavenetA", "punetB", "rnnC", "fnoD"):
            (registry / f"{design}.json").write_text("{}\n")

        band = _bash(
            str(STAGE1_BAND),
            "--band",
            "0-3",
            "--workspace_root",
            str(workspace),
            "--arm",
            "blindpod",
            "--dry-run",
        )
        assert band.returncode != 0, band.stdout
        assert GENERATED_LIBRARY_ENV_VAR in band.stderr

        unit = _bash(
            str(STAGE2),
            "--workspace_root",
            str(workspace),
            "--arm",
            "blindpod",
            "--design_registry",
            str(registry),
            "--dry-run",
        )
        assert unit.returncode != 0, unit.stdout
        assert GENERATED_LIBRARY_ENV_VAR in unit.stderr

    def test_the_launchers_requirement_and_the_production_authority_agree(
        self, workspace, advice, tmp_path
    ):
        """The defect only this catches: the launcher demanding a variable
        that production does not actually resolve from — the F-*-WIRE class
        itself, one layer up. A launcher can refuse loudly on a name nothing
        reads and look perfectly correct.

        Asserted against the production authority whose output the
        run-invariants lock stores verbatim, NEVER against R8 (which globs
        the checkout dir and is blind to this root).

        Fails by: the launcher accepting a value that the authority does not
        resolve to, or resolving it with source != 'env'."""
        lib = tmp_path / "campaign_library"
        lib.mkdir()
        proc = _stage1_dry(workspace, advice, **{GENERATED_LIBRARY_ENV_VAR: str(lib)})
        assert proc.returncode == 0, proc.stderr

        provenance = generated_library_provenance(environ={GENERATED_LIBRARY_ENV_VAR: str(lib)})
        assert provenance == {"root": str(lib), "source": "env"}, provenance

        # And the launcher's rejected state is the one the authority calls
        # "default" — the two layers disagree about nothing.
        unset = generated_library_provenance(environ={})
        assert unset["source"] == "default"
        assert unset["root"] != str(lib)

    @pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
    def test_a_blank_value_is_not_a_declaration(self, workspace, advice, raw):
        """The defect only this catches: the launcher accepting whitespace
        that the production authority strips back to 'unset'. The two layers
        would then disagree — the launcher reports a bound library while
        production resolves the shared default.

        Fails by: a blank value passing the launcher."""
        proc = _stage1_dry(workspace, advice, **{GENERATED_LIBRARY_ENV_VAR: raw})
        assert proc.returncode != 0, proc.stdout
        assert GENERATED_LIBRARY_ENV_VAR in proc.stderr
        # The authority agrees this is not a declaration.
        assert (
            generated_library_provenance(environ={GENERATED_LIBRARY_ENV_VAR: raw})["source"]
            == "default"
        )


def _r1c_rows(env: dict[str, str] | None) -> list[str]:
    """Run the preflight and return only its R1c verdict rows.

    The overall preflight exit status is deliberately NOT asserted: other
    rows (dataset availability, a clean tree, LLM smoke) depend on the host
    and on the working tree being committed, and are owned elsewhere. What
    this file owns is R1c's verdict.
    """
    revision = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    proc = _bash(
        str(PREFLIGHT),
        "--workspace-root",
        str(REPO_ROOT / ".git"),  # an existing, writable, persistent dir
        "--arm",
        "without-prior-art",
        "--revision",
        revision,
        "--skip_llm_smoke",
        "--",
        "--healthgate_mode",
        "blocking",
        "--result_authority",
        "scientific",
        env=env,
    )
    return [
        line
        for line in (proc.stdout + proc.stderr).splitlines()
        if "R1c" in line and ("PASS" in line or "FAIL" in line)
    ]


class TestPreflightR1cValidatesTheSuppliedRoot:
    def test_r1c_fails_when_the_variable_is_unset(self):
        """The defect only this catches: preflight passing a campaign whose
        library resolves to the shared default root. R1b already checks the
        calibration store this way; the generated library had no such row,
        and R8 cannot supply one because it globs the checkout only.

        Fails by: no FAIL row, or a message that does not name the default
        resolution as the reason."""
        rows = _r1c_rows(None)
        assert rows, "R1c produced no verdict"
        assert all("FAIL" in row for row in rows), rows
        assert any("DEFAULT root" in row for row in rows), rows

    def test_r1c_passes_for_a_persistent_supplied_root(self, tmp_path):
        """The defect only this catches: a guard that fails closed on
        everything, which would make every campaign unlaunchable and be
        disabled within a day.

        Fails by: a FAIL row for a supplied root on a persistent
        filesystem."""
        lib = tmp_path / "campaign_library"
        lib.mkdir()
        rows = _r1c_rows({GENERATED_LIBRARY_ENV_VAR: str(lib)})
        assert rows, "R1c produced no verdict"
        assert all("PASS" in row for row in rows), rows
        assert any("source=env" in row for row in rows), rows

    def test_r1c_fails_when_the_production_authority_refuses_the_value(self):
        """The defect only this catches: R1c re-deriving the root in bash
        instead of calling the authority. A bash re-implementation would
        happily accept a RELATIVE path that
        `core.generated_library.resolve_generated_library` refuses — two
        authorities, free to drift, and the preflight would bless a value the
        run then rejects (or worse, anchors to the launch cwd).

        Fails by: a PASS row for a value the authority refuses."""
        rows = _r1c_rows({GENERATED_LIBRARY_ENV_VAR: "relative/library"})
        assert rows, "R1c produced no verdict"
        assert all("FAIL" in row for row in rows), rows
        assert any("could not be resolved" in row for row in rows), rows
