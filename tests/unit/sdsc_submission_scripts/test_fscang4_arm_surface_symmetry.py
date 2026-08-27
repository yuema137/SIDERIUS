"""F-SCANG-4 — the symmetry gate can now see the routes that actually differ.

The frozen row's requirement has three clauses, and each names a route the
argv-only gate was blind to:

    The gate must compare RENDERED PROMPT BYTES between arms, not argv, and
    must cover the environment and the machine-local stores. Otherwise
    section 10 cannot honestly claim arm symmetry was verified.

The gate's two original layers are both argv — a resolved-config JSON and a
child command line, produced by "two HYPOTHETICAL COMMAND LINES on ONE
MACHINE". ``campaign_arm_surface.py`` captures the three missing routes for
one arm; ``campaign_arm_symmetry.check_surfaces`` compares two captures.

Each test names the defect only it catches.

* ``TestStoreDigestPortability`` — the digest of a machine-local store must
  be a function of CONTENT, not of where the store is mounted. If an
  absolute path entered the hash, EVERY cross-pod comparison would be red,
  the operator would switch the layer off, and the row would reopen wearing
  a green check. Discrimination: one changed byte must move the digest.
* ``TestEnvironmentCapture`` — the declared capture rule, asserted by
  positive membership against a synthetic environ carrying decoys. A
  prefix that stopped matching would silently shrink the captured
  population to nothing, and "no environment difference" would then be true
  for free. Secret-shaped names must record presence WITHOUT the value:
  this artifact is copied into a launch packet.
* ``TestSurfaceContract`` — ``build_surface`` refuses an undeclared or
  unresolved store id. A store silently dropped at capture time is a store
  the comparator can never find missing.
* ``TestPromptByteSymmetry`` — clause 1. The NEUTRAL render (both arms at
  ``baseline_isolation=False``) must be byte-identical, because with the
  treatment held constant only machine-local state can move it; the ARM
  render must differ on the declared treatment surfaces, because two arms
  rendering identical prompts are mis-wired, not symmetric. Both directions
  are exercised, plus the missing-surface case that would otherwise let a
  renamed surface shrink what the gate can see.
* ``TestEnvironmentSymmetry`` / ``TestStoreSymmetry`` — clauses 2 and 3,
  each with its legal PASS case (a DECLARED arm-local variable, the
  observed-only calibration store) and its targeted FAIL case. A layer that
  only ever passes is not evidence; a layer that fails on the legitimate
  per-arm GPU assignment would be switched off within a day.
* ``TestDeclaredPolicy`` — the classification tables, hardcoded. Reading
  them back out of the module would compare the policy to itself.
* ``TestTheSurfaceLayerCannotBeSkipped`` — ``--with-surface`` /
  ``--without-surface`` are REQUIRED. Optional would mean a preflight that
  forgot them still prints "arm symmetry holds" from argv alone — precisely
  the claim the row says cannot honestly be made.
* ``TestProductionWitness`` — the reachability evidence. A contaminated
  generated library on ONE arm is captured by the REAL
  ``campaign_arm_surface.py``, reaches the REAL rendered prompt bytes, and
  turns the REAL ``campaign_arm_symmetry.py`` red on both the store row and
  the prompt row. No synthetic dict anywhere in this test.
* ``TestPreflightWiring`` — R7 actually invokes the capture, publishes the
  surface into the shared campaign root (what makes the comparison
  cross-pod) and passes both surfaces to the checker; the arm's isolation
  flag is READ from its own resolved-config print rather than re-derived;
  and the gold arm still SKIPS the whole row, because Gold<->Blind
  treatment symmetry is a separate blind-launch prerequisite this script
  deliberately does not serve.

No GPU, no LLM, no training.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SDSC = REPO_ROOT / "sdsc_submission_scripts"
SURFACE_SCRIPT = SDSC / "campaign_arm_surface.py"
SYMMETRY_SCRIPT = SDSC / "campaign_arm_symmetry.py"
PREFLIGHT = SDSC / "campaign_preflight.sh"


def _load(path: Path, name: str) -> ModuleType:
    """Import a sdsc_submission_scripts module from THIS checkout.

    The directory is not a package, so the module is loaded by file
    location derived from this test's own path — never by a name that
    could resolve into another clone.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


surface_mod = _load(SURFACE_SCRIPT, "_fscang4_surface")
symmetry_mod = _load(SYMMETRY_SCRIPT, "_fscang4_symmetry")

ARMS = ("with-prior-art", "without-prior-art")

#: Every prompt surface id the capture produces. Hardcoded: the comparator's
#: policy is expressed in these strings, and deriving them from the capture
#: would let a rename pass unnoticed on both sides at once.
ALL_SURFACE_IDS = (
    "proposal.available_losses_block",
    "proposal.available_models_block",
    "proposal.stage.causal_reasoning_stage.exploit",
    "proposal.stage.causal_reasoning_stage.explore",
    "proposal.stage.comparison_stage.exploit",
    "proposal.stage.comparison_stage.explore",
    "proposal.stage.proposing_stage.exploit",
    "proposal.stage.proposing_stage.explore",
    "proposal.task_blocks",
    "task.forward_contract",
    "task.task_description",
)

MUST_DIFFER = symmetry_mod.PROMPT_SURFACES_MUST_DIFFER


def _digest(marker: str) -> dict:
    return {"sha256": hashlib.sha256(marker.encode()).hexdigest(), "bytes": len(marker)}


def _store(marker: str, entries: int = 3) -> dict:
    return {
        "present": True,
        "entry_count": entries,
        "content_sha256": hashlib.sha256(marker.encode()).hexdigest(),
        "sample": [],
    }


def make_surface(
    arm: str,
    *,
    prompts: dict | None = None,
    environment: dict | None = None,
    stores: dict | None = None,
) -> dict:
    """A synthetic, SYMMETRIC arm surface — the baseline every FAIL case
    perturbs by exactly one field, so a red verdict names one cause."""
    prompt_bytes = {}
    for surface_id in ALL_SURFACE_IDS:
        arm_marker = (
            f"arm::{arm}::{surface_id}" if surface_id in MUST_DIFFER else f"n::{surface_id}"
        )
        prompt_bytes[surface_id] = {
            "arm": _digest(arm_marker),
            "neutral": _digest(f"n::{surface_id}"),
        }
    if prompts:
        prompt_bytes.update(prompts)
    base_stores = {
        "generated_library": _store("genlib-empty", 0),
        "checkout_capability_state": _store("checkout-clean", 0),
        "root_papers_cache": _store("papers", 2),
        "calibration_store": _store(f"calib::{arm}", 40),
    }
    if stores is not None:
        base_stores.update(stores)
    return {
        "schema": surface_mod.SURFACE_SCHEMA,
        "arm": arm,
        "baseline_isolation": arm == "without-prior-art",
        "prompt_bytes": prompt_bytes,
        "environment": (
            {"PYTHONPATH": "/repo", "SIDERIUS_TASK": "tidmad"}
            if environment is None
            else environment
        ),
        "machine_local_stores": base_stores,
    }


def _check(with_kwargs: dict | None = None, without_kwargs: dict | None = None) -> list[str]:
    return symmetry_mod.check_surfaces(
        make_surface(ARMS[0], **(with_kwargs or {})),
        make_surface(ARMS[1], **(without_kwargs or {})),
    )


class TestStoreDigestPortability:
    def test_the_same_store_at_two_absolute_paths_digests_identically(self, tmp_path):
        """The cross-pod comparison depends on this. Fails when an absolute
        path enters the hash — every pod pair would then read as
        contaminated and the layer would be disabled."""
        a, b = tmp_path / "podA" / "lib", tmp_path / "podB" / "elsewhere" / "lib"
        for root in (a, b):
            (root / "losses").mkdir(parents=True)
            (root / "losses" / "custom.py").write_text("def loss(): ...\n")
            (root / "_capability_index.json").write_text("[]\n")
        first = surface_mod.digest_paths([("generated_library", str(a))])
        second = surface_mod.digest_paths([("generated_library", str(b))])
        assert first["content_sha256"] == second["content_sha256"]
        assert first["entry_count"] == 2

    def test_one_changed_byte_moves_the_digest(self, tmp_path):
        """Discrimination: a digest that cannot change cannot detect."""
        root = tmp_path / "lib"
        root.mkdir()
        (root / "f.py").write_text("A")
        before = surface_mod.digest_paths([("lib", str(root))])["content_sha256"]
        (root / "f.py").write_text("B")
        after = surface_mod.digest_paths([("lib", str(root))])["content_sha256"]
        assert before != after

    def test_a_renamed_file_moves_the_digest(self, tmp_path):
        """Structure counts too: a promoted capability under a new name is
        a different prompt surface even at identical content."""
        root = tmp_path / "lib"
        root.mkdir()
        (root / "a.py").write_text("X")
        before = surface_mod.digest_paths([("lib", str(root))])["content_sha256"]
        (root / "a.py").rename(root / "b.py")
        assert surface_mod.digest_paths([("lib", str(root))])["content_sha256"] != before

    def test_an_absent_store_is_reported_absent_not_empty(self, tmp_path):
        entry = surface_mod.digest_paths([("lib", str(tmp_path / "nope"))])
        assert entry["present"] is False
        assert entry["entry_count"] == 0


class TestEnvironmentCapture:
    def test_the_declared_prefixes_and_names_are_captured_and_nothing_else(self):
        """Positive membership against decoys. A prefix tuple that stopped
        matching would make 'the environments agree' true for free."""
        captured = surface_mod.capture_environment(
            {
                "SIDERIUS_CALIBRATION_DIR": "/persist/cal",
                "TIDMAD_DATA_DIR": "/data",
                "H100_CORESIDENCY_FACTOR": "2.4",
                "VALIDATION_FIXED_CANDIDATE_PLAN": "/tmp/evil.json",
                "PYTHONPATH": "/repo",
                "CUDA_VISIBLE_DEVICES": "0",
                "OMP_NUM_THREADS": "8",
                "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:128",
                "CHAIN_STOP_FILE": "/ws/STOP",
                # decoys: real environment noise that must never be compared
                "HOSTNAME": "podA",
                "PWD": "/root",
                "LS_COLORS": "rs=0",
                "SSH_CONNECTION": "10.0.0.1 22",
            }
        )
        assert set(captured) == {
            "SIDERIUS_CALIBRATION_DIR",
            "TIDMAD_DATA_DIR",
            "H100_CORESIDENCY_FACTOR",
            "VALIDATION_FIXED_CANDIDATE_PLAN",
            "PYTHONPATH",
            "CUDA_VISIBLE_DEVICES",
            "OMP_NUM_THREADS",
            "PYTORCH_CUDA_ALLOC_CONF",
            "CHAIN_STOP_FILE",
        }
        assert captured["TIDMAD_DATA_DIR"] == "/data"

    def test_a_secret_shaped_name_records_presence_without_its_value(self):
        """This artifact is published into a shared campaign root and
        copied into a launch packet. Fails by leaking the value."""
        captured = surface_mod.capture_environment({"SIDERIUS_PROVIDER_API_KEY": "sk-real-secret"})
        assert captured["SIDERIUS_PROVIDER_API_KEY"] == surface_mod.SECRET_PLACEHOLDER
        assert "sk-real-secret" not in json.dumps(captured)

    def test_the_f_scani2_injection_names_are_inside_the_captured_population(self):
        """The VALIDATION_ prefix is captured on purpose: an export of one
        of those on ONE arm is an asymmetry worth naming, and F-SCANI-2
        closed the route it would otherwise take into the child argv."""
        assert "VALIDATION_" in surface_mod.ENVIRONMENT_PREFIXES


class TestSurfaceContract:
    def test_an_undeclared_store_id_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            surface_mod, "render_prompt_surfaces", lambda **_: {"x": "y"}, raising=True
        )
        stores = {sid: [] for sid in surface_mod.STORE_IDS}
        stores["a_store_nobody_declared"] = []
        with pytest.raises(ValueError, match="undeclared store id"):
            surface_mod.build_surface(
                arm=ARMS[0], baseline_isolation=False, environ={}, stores=stores
            )

    def test_a_missing_store_id_is_refused(self, monkeypatch):
        """A store silently dropped at capture is a store the comparator can
        never find missing — the capture must refuse first."""
        monkeypatch.setattr(
            surface_mod, "render_prompt_surfaces", lambda **_: {"x": "y"}, raising=True
        )
        stores = {sid: [] for sid in surface_mod.STORE_IDS if sid != "root_papers_cache"}
        with pytest.raises(ValueError, match="not resolved"):
            surface_mod.build_surface(
                arm=ARMS[0], baseline_isolation=False, environ={}, stores=stores
            )

    def test_an_unknown_arm_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            surface_mod, "render_prompt_surfaces", lambda **_: {"x": "y"}, raising=True
        )
        with pytest.raises(ValueError, match="unknown arm"):
            surface_mod.build_surface(
                arm="goldpod",
                baseline_isolation=False,
                environ={},
                stores={sid: [] for sid in surface_mod.STORE_IDS},
            )


class TestPromptByteSymmetry:
    def test_a_symmetric_pair_passes(self):
        assert _check() == []

    def test_a_divergent_neutral_render_is_caught_and_named(self):
        """Clause 1, the contamination direction. The neutral render holds
        the treatment identical, so a difference can only come from the
        machine — a promoted loss visible to one arm's proposer and not the
        other's. Fails by naming the surface and both digests."""
        contaminated = {
            "proposal.available_losses_block": {
                "arm": _digest("n::proposal.available_losses_block"),
                "neutral": _digest("contaminated-by-a-leaked-loss"),
            }
        }
        problems = _check(without_kwargs={"prompts": contaminated})
        assert any(
            "proposal.available_losses_block" in p and "NEUTRAL render differs" in p
            for p in problems
        ), problems

    def test_identical_treatment_surfaces_are_mis_wired_not_symmetric(self):
        """Clause 1, the non-vacuity direction. Two arms whose isolation
        renders agree are not a symmetric experiment; they are one arm run
        twice, and the argv layer would still call that PASS."""
        same = {
            sid: {"arm": _digest(f"n::{sid}"), "neutral": _digest(f"n::{sid}")}
            for sid in MUST_DIFFER
        }
        problems = _check(with_kwargs={"prompts": same}, without_kwargs={"prompts": same})
        assert len(problems) >= len(MUST_DIFFER)
        assert all(any(sid in p for p in problems) for sid in MUST_DIFFER)
        assert any("mis-wired" in p for p in problems)

    def test_a_declared_treatment_surface_missing_from_the_capture_is_caught(self):
        """A renamed or dropped surface must not quietly shrink what the
        gate can see. Positive membership, enforced at compare time."""
        with_surface = make_surface(ARMS[0])
        without_surface = make_surface(ARMS[1])
        for surf in (with_surface, without_surface):
            del surf["prompt_bytes"]["proposal.available_models_block"]
        problems = symmetry_mod.check_surfaces(with_surface, without_surface)
        assert any("proposal.available_models_block" in p and "absent" in p for p in problems), (
            problems
        )

    def test_a_surface_present_on_one_arm_only_is_caught(self):
        without_surface = make_surface(ARMS[1])
        del without_surface["prompt_bytes"]["task.task_description"]
        problems = symmetry_mod.check_surfaces(make_surface(ARMS[0]), without_surface)
        assert any("task.task_description" in p for p in problems), problems

    def test_an_empty_prompt_section_is_caught_rather_than_passing(self):
        """The classic vacuous green: nothing captured, nothing differs."""
        a, b = make_surface(ARMS[0]), make_surface(ARMS[1])
        a["prompt_bytes"] = {}
        b["prompt_bytes"] = {}
        problems = symmetry_mod.check_surfaces(a, b)
        assert any("nothing was compared" in p for p in problems), problems


class TestEnvironmentSymmetry:
    def test_an_undeclared_environment_difference_is_caught(self):
        """Clause 2, fail-closed. An unknown SIDERIUS_* export that differs
        between pods is the failure class; allow-by-omission would make the
        layer decorative."""
        problems = _check(
            with_kwargs={"environment": {"SIDERIUS_TASK": "tidmad"}},
            without_kwargs={"environment": {"SIDERIUS_TASK": "something-else"}},
        )
        assert any("environment SIDERIUS_TASK" in p for p in problems), problems

    def test_a_variable_present_on_one_arm_only_is_caught(self):
        problems = _check(
            with_kwargs={"environment": {"TIDMAD_PROFILE": "campaign"}},
            without_kwargs={"environment": {}},
        )
        assert any("environment TIDMAD_PROFILE" in p for p in problems), problems

    def test_a_declared_arm_local_variable_may_differ(self):
        """Discrimination. The campaign assigns one card per arm; a gate
        that failed on that would be switched off within a day."""
        problems = _check(
            with_kwargs={"environment": {"CUDA_VISIBLE_DEVICES": "0"}},
            without_kwargs={"environment": {"CUDA_VISIBLE_DEVICES": "1"}},
        )
        assert problems == []


class TestStoreSymmetry:
    def test_a_required_store_content_difference_is_caught(self):
        """Clause 3. A generated library holding one arm's promoted
        capabilities is exactly R1c's contamination, and R8 cannot see it:
        R8 globs the CHECKOUT dir only."""
        problems = _check(
            without_kwargs={"stores": {"generated_library": _store("leaked-capability", 5)}}
        )
        assert any("generated_library" in p and "content differs" in p for p in problems), problems

    def test_the_checkout_capability_state_is_required_symmetric(self):
        problems = _check(
            without_kwargs={"stores": {"checkout_capability_state": _store("leftover-plugin", 1)}}
        )
        assert any("checkout_capability_state" in p for p in problems), problems

    def test_the_root_paper_cache_is_required_symmetric(self):
        """It feeds the WITH arm's expert context — a prompt surface."""
        problems = _check(without_kwargs={"stores": {"root_papers_cache": _store("other", 9)}})
        assert any("root_papers_cache" in p for p in problems), problems

    def test_the_calibration_store_may_differ(self):
        """Discrimination, and a NARROW exemption: per-device measured
        k-tables SHOULD disagree between two cards, and the cold-start
        checklist RETAINs the store by design (R8 item6). It reaches the
        watchdog, never a prompt."""
        assert _check() == []
        assert "calibration_store" in symmetry_mod.STORE_SYMMETRY_OBSERVED

    def test_an_unclassified_store_must_be_classified_before_launch(self):
        """A new store added to the capture with no symmetry policy is not
        thereby symmetric. Fails by naming it."""
        extra = {"a_new_store": _store("x")}
        problems = _check(with_kwargs={"stores": extra}, without_kwargs={"stores": extra})
        assert any("a_new_store" in p and "not classified" in p for p in problems), problems

    def test_a_declared_store_missing_from_the_capture_is_caught(self):
        a, b = make_surface(ARMS[0]), make_surface(ARMS[1])
        for surf in (a, b):
            del surf["machine_local_stores"]["root_papers_cache"]
        problems = symmetry_mod.check_surfaces(a, b)
        assert any("root_papers_cache" in p and "missing" in p for p in problems), problems

    def test_an_unhashable_store_fails_rather_than_comparing_absent_digests(self):
        """Two stores that both refused to hash have equal (absent) digests.
        Without this the refusal would read as agreement."""
        problems = _check(
            with_kwargs={"stores": {"generated_library": {"present": True, "error": "too large"}}},
            without_kwargs={
                "stores": {"generated_library": {"present": True, "error": "too large"}}
            },
        )
        assert any("too large" in p for p in problems), problems


class TestDeclaredPolicy:
    def test_the_treatment_surfaces_are_exactly_the_isolation_sensitive_ones(self):
        """Hardcoded. arXiv U3 makes the models block and every stage
        template isolation-sensitive; reading the set back out of the
        module would compare the policy to itself."""
        assert MUST_DIFFER == frozenset(
            {
                "proposal.available_models_block",
                "proposal.stage.comparison_stage.explore",
                "proposal.stage.comparison_stage.exploit",
                "proposal.stage.causal_reasoning_stage.explore",
                "proposal.stage.causal_reasoning_stage.exploit",
                "proposal.stage.proposing_stage.explore",
                "proposal.stage.proposing_stage.exploit",
            }
        )

    def test_the_store_classification_partitions_every_declared_store(self):
        required = symmetry_mod.STORE_SYMMETRY_REQUIRED
        observed = symmetry_mod.STORE_SYMMETRY_OBSERVED
        assert required == frozenset(
            {"generated_library", "checkout_capability_state", "root_papers_cache"}
        )
        assert observed == frozenset({"calibration_store"})
        assert required & observed == frozenset()
        assert required | observed == set(surface_mod.STORE_IDS)

    def test_the_arm_local_environment_allowlist_is_exactly_these_names(self):
        """Every entry here is a hole in clause 2, so the list is pinned by
        name. Fails when one is added without an operator decision."""
        assert set(symmetry_mod.ENVIRONMENT_ARM_LOCAL) == {
            "CUDA_VISIBLE_DEVICES",
            "SIDERIUS_CHAIN_WORKSPACE",
            "SIDERIUS_GENERATED_LIBRARY_DIR",
            "SIDERIUS_CALIBRATION_DIR",
            "SIDERIUS_LIVE_CALIBRATION_DIR",
        }

    def test_a_mispaired_surface_is_refused_before_anything_is_compared(self):
        """Two captures of the SAME arm would agree on everything. The
        gate must name the pairing error, not print PASS."""
        problems = symmetry_mod.check_surfaces(make_surface(ARMS[0]), make_surface(ARMS[0]))
        assert any("paired wrongly" in p for p in problems), problems


def _run_symmetry_cli(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    (tmp_path / "with.out").write_text("")
    (tmp_path / "without.out").write_text("")
    return subprocess.run(
        [
            sys.executable,
            str(SYMMETRY_SCRIPT),
            "--with-output",
            str(tmp_path / "with.out"),
            "--without-output",
            str(tmp_path / "without.out"),
            "--workspace-root",
            "/persist/camp",
            "--band",
            "0-3",
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestTheSurfaceLayerCannotBeSkipped:
    def test_the_surface_arguments_are_required(self, tmp_path):
        """An OPTIONAL layer 3 is one a preflight can forget, and a
        forgotten layer 3 prints 'arm symmetry holds' from argv alone —
        the claim the row says section 10 cannot honestly make."""
        result = _run_symmetry_cli(tmp_path)
        assert result.returncode != 0
        assert "--with-surface" in result.stderr

    def test_an_unknown_surface_schema_is_refused_not_compared(self, tmp_path):
        for name in ("s_with.json", "s_without.json"):
            (tmp_path / name).write_text(json.dumps({"schema": "something/else"}))
        result = _run_symmetry_cli(
            tmp_path,
            "--with-surface",
            str(tmp_path / "s_with.json"),
            "--without-surface",
            str(tmp_path / "s_without.json"),
        )
        assert result.returncode == 2
        assert "unknown surface schema" in result.stderr


def _dry_run_capture(arm: str) -> str:
    """A minimal but REAL-shaped launcher capture: the argv layer must be
    able to pass so the surface layer's verdict is the one under test."""
    root, band = "/persist/camp", "0-3"
    policy = {
        "with-prior-art": {
            "experiment_arm": "with-prior-art",
            "lit_review_enabled": True,
            "lit_review_config_path": "/repo/configs/lit_review_config.yaml",
            "lit_review_config_sha256": "ab" * 32,
            "baseline_isolation": False,
        },
        "without-prior-art": {
            "experiment_arm": "without-prior-art",
            "lit_review_enabled": False,
            "lit_review_config_path": "/repo/configs/lit_review_config.yaml",
            "lit_review_config_sha256": None,
            "baseline_isolation": True,
        },
    }[arm]
    cfg = {
        "workspace": f"{root}/{arm}_band{band}",
        "run_name": f"{arm}_band{band}",
        "start_iteration": 1,
        "healthgate_mode": "blocking",
        "result_authority": "scientific",
        **policy,
    }
    arm_tokens = (
        "--ml_lit_review_enabled --experiment_arm with-prior-art"
        if arm == "with-prior-art"
        else "--no-ml_lit_review_enabled --experiment_arm without-prior-art --baseline_isolation"
    )
    return (
        "[prior-baseline] resolved launch configuration:\n"
        + json.dumps(cfg, indent=2, sort_keys=True)
        + "\n  [DRY-RUN] would exec from /repo:\n"
        + "    /venv/bin/python /repo/sdsc_submission_scripts/run_one_iteration.py "
        + f"--workspace {root}/{arm}_band{band} --run_name {arm}_band{band} "
        + f"--data_scope {band} --formal_portion 0.1 {arm_tokens}\n"
    )


class TestProductionWitness:
    """The reachability evidence: the REAL capture, the REAL renderers, the
    REAL checker. Nothing synthetic."""

    @staticmethod
    def _capture(tmp_path: Path, arm: str, isolation: str, library: Path) -> Path:
        out = tmp_path / f"surface_{arm}.json"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        env["SIDERIUS_GENERATED_LIBRARY_DIR"] = str(library)
        result = subprocess.run(
            [
                sys.executable,
                str(SURFACE_SCRIPT),
                "--arm",
                arm,
                "--baseline-isolation",
                isolation,
                "--project-dir",
                str(REPO_ROOT),
                "--out",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(REPO_ROOT),
            env=env,
        )
        assert result.returncode == 0, result.stderr
        return out

    @staticmethod
    def _library(root: Path, *, contaminated: bool) -> Path:
        (root / "losses").mkdir(parents=True)
        entries = []
        if contaminated:
            plugin = root / "losses" / "leaked_campaign_loss.py"
            plugin.write_text("def leaked_campaign_loss():\n    ...\n")
            entries.append(
                {
                    "name": "leaked_campaign_loss",
                    "capability_type": "loss",
                    "source_iteration": "4",
                    "description": "promoted by an EARLIER campaign on this pod",
                    "created_at": "2026-08-01T00:00:00Z",
                    "file_path": str(plugin),
                    "mathematical_definition": "",
                }
            )
        (root / "_capability_index.json").write_text(json.dumps(entries))
        return root

    def test_a_contaminated_library_reaches_the_prompt_and_turns_the_gate_red(self, tmp_path):
        """The whole chain, end to end: a promoted capability left on ONE
        pod's generated-library mount changes what that arm's proposer is
        told, and the gate names BOTH the store and the prompt surface.
        Before F-SCANG-4 the same pair passed — the argv is identical, and
        argv is all the gate compared."""
        clean = self._library(tmp_path / "clean_lib", contaminated=False)
        dirty = self._library(tmp_path / "dirty_lib", contaminated=True)
        with_surface = self._capture(tmp_path, ARMS[0], "false", clean)
        without_surface = self._capture(tmp_path, ARMS[1], "true", dirty)

        (tmp_path / "with.out").write_text(_dry_run_capture(ARMS[0]))
        (tmp_path / "without.out").write_text(_dry_run_capture(ARMS[1]))
        result = subprocess.run(
            [
                sys.executable,
                str(SYMMETRY_SCRIPT),
                "--with-output",
                str(tmp_path / "with.out"),
                "--without-output",
                str(tmp_path / "without.out"),
                "--workspace-root",
                "/persist/camp",
                "--band",
                "0-3",
                "--with-surface",
                str(with_surface),
                "--without-surface",
                str(without_surface),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "generated_library" in result.stderr, result.stderr
        assert "proposal.available_losses_block" in result.stderr, result.stderr
        assert "NEUTRAL render differs" in result.stderr, result.stderr

    def test_two_identical_libraries_leave_the_surface_layer_green(self, tmp_path):
        """Discrimination for the witness above: the same two arms with
        equal machine-local state must PASS, or the red result proves
        nothing about contamination."""
        a = self._library(tmp_path / "libA", contaminated=False)
        b = self._library(tmp_path / "libB", contaminated=False)
        with_surface = json.loads(self._capture(tmp_path, ARMS[0], "false", a).read_text())
        without_surface = json.loads(self._capture(tmp_path, ARMS[1], "true", b).read_text())
        # SIDERIUS_GENERATED_LIBRARY_DIR is a DECLARED arm-local variable
        # (per-arm roots are what keep one arm's promotions out of the
        # other's proposer), so the two differing paths are legal and the
        # content digests are what must agree.
        assert symmetry_mod.check_surfaces(with_surface, without_surface) == []


class TestPreflightWiring:
    @pytest.fixture(scope="class")
    def preflight_text(self) -> str:
        return PREFLIGHT.read_text(encoding="utf-8")

    def test_r7_captures_publishes_and_compares_the_surface(self, preflight_text):
        """Reachability: a capture module nobody invokes is not a gate.
        Publication into the shared campaign root is what makes the sibling
        surface come from the OTHER POD rather than from this one."""
        assert "campaign_arm_surface.py" in preflight_text
        assert "--with-surface" in preflight_text
        assert "--without-surface" in preflight_text
        assert ".campaign_arm_surface_${ARM}.json" in preflight_text
        assert ".campaign_arm_surface_${OTHER_ARM}.json" in preflight_text

    def test_a_local_sibling_surface_is_reported_as_weaker_evidence(self, preflight_text):
        """Same-host capture cannot speak for a second pod, and the row's
        whole complaint is a gate that says more than it proved."""
        assert "--surface-provenance" in preflight_text
        assert "cannot speak for a second pod" in preflight_text

    @pytest.mark.parametrize(
        "capture,expected",
        [
            ('  "baseline_isolation": true,\n', "true"),
            ('  "baseline_isolation": false,\n', "false"),
            ('  "baseline_isolation":false\n', "false"),
        ],
    )
    def test_the_isolation_flag_is_read_from_the_resolved_config(self, tmp_path, capture, expected):
        """Read, never re-derived: the launcher owns the arm -> isolation
        mapping, and a second table here could render the treatment this
        script believes in rather than the one the run applies."""
        path = tmp_path / "cap.out"
        path.write_text('{\n  "experiment_arm": "x",\n' + capture + "}\n")
        result = subprocess.run(
            ["bash", "-c", f'source "{PREFLIGHT}"\npreflight_resolved_isolation "{path}"\n'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected

    def test_a_capture_without_the_field_refuses_rather_than_defaulting(self, tmp_path):
        """An absent flag must not silently become 'false' — that would
        render BOTH arms un-isolated and the treatment would vanish from
        the comparison while the row still read PASS."""
        path = tmp_path / "cap.out"
        path.write_text("{}\n")
        result = subprocess.run(
            ["bash", "-c", f'source "{PREFLIGHT}"\npreflight_resolved_isolation "{path}"\n'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 1
        assert result.stdout.strip() == ""

    @pytest.mark.parametrize(
        "arm,expected", [("with-prior-art", "false"), ("without-prior-art", "true")]
    )
    def test_the_isolation_value_is_selected_by_arm(self, arm, expected):
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{PREFLIGHT}"\npreflight_isolation_for_arm {arm} false true\n',
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected

    def test_the_gold_arm_still_skips_the_whole_row(self, tmp_path):
        """The boundary. Gold<->Blind treatment symmetry is a separate
        blind-launch prerequisite; F-SCANG-4 extends what R7 compares for
        the X9 pair and must NOT quietly start reporting on the campaign
        arms. Fails if the surface layer runs under --arm goldpod."""
        sdsc = tmp_path / "sdsc"
        sdsc.mkdir()
        for name in (
            "campaign_preflight.sh",
            "_import_resolution_probe.py",
            "h100_posture.env",
            "campaign_arm_symmetry.py",
            "campaign_arm_surface.py",
        ):
            shutil.copy2(SDSC / name, sdsc / name)
        launcher = sdsc / "launch_prior_baseline_experiment.sh"
        launcher.write_text("#!/bin/sh\nexit 0\n")
        launcher.chmod(0o755)
        fake_python = tmp_path / "fakepython"
        fake_python.write_text("#!/bin/sh\nexit 1\n")
        fake_python.chmod(0o755)
        root = tmp_path / "root"
        root.mkdir()
        result = subprocess.run(
            [
                "bash",
                str(sdsc / "campaign_preflight.sh"),
                "--workspace-root",
                str(root),
                "--arm",
                "goldpod",
                "--revision",
                "deadbeefcafe",
                "--skip_llm_smoke",
                "--",
                "--healthgate_mode",
                "blocking",
                "--result_authority",
                "scientific",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(tmp_path),
                "SIDERIUS_PYTHON": str(fake_python),
            },
        )
        r7_rows = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip().split(None, 2)[:2] in (["SKIP", "R7"], ["PASS", "R7"], ["FAIL", "R7"])
        ]
        assert r7_rows, result.stdout
        assert all(row.startswith("SKIP") for row in r7_rows), r7_rows
        assert not list(root.glob(".campaign_arm_surface_*.json")), (
            "a gold preflight must not publish an arm surface"
        )
