"""arXiv U1 (#253 / #254) — chain-runner wiring of run identity.

What only these tests catch:

* ``TestLockSiteCensus`` — the PR 2 lock-collision failure mode for the
  canonical launch-identity fields: a ``build_run_invariants(`` site relying
  on builder defaults would write a lock contradicting the chain's and abort
  every labelled or literature-review-enabled run. A new production caller
  cannot appear unnoticed.
* ``TestChainCli`` / ``TestLaunchIdentityResolution`` — the resolution
  order (CLI > YAML > off), the sha being the resolved FILE's bytes, and
  an enabled-but-unreadable config being refused before any work.
* ``TestManifestIdentityStamps`` — the three keys on EVERY manifest branch
  under the lock's omission rule; an unlabelled lit-review-OFF manifest is
  key-for-key identical to a call that predates the parameter.
* ``TestShellForwarding`` — ``_chain_common.sh`` forwards ``--experiment_arm``
  only when set (an unlabelled chain's argv is byte-identical to pre-U1).
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_spec = importlib.util.spec_from_file_location(
    "run_one_iteration_for_identity_test",
    _REPO / "sdsc_submission_scripts" / "run_one_iteration.py",
)
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)

_CHAIN_COMMON = _REPO / "sdsc_submission_scripts" / "_chain_common.sh"

LOCK_SITES = {
    "tuner": _REPO / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
    "workflow": _REPO / "workflows/model_exploration.py",
    "chain": _REPO / "sdsc_submission_scripts/run_one_iteration.py",
}

IDENTITY_KWARGS = (
    "lit_review_enabled=",
    "lit_review_config_sha256=",
    "experiment_arm=",
    # arXiv U3 — the isolation flag is locked at the same three sites.
    "baseline_isolation=",
)

_BASE_ARGV = [
    "--workspace",
    "/tmp/ws",
    "--start_iteration",
    "1",
    "--run_name",
    "t",
    "--task_composition",
    str(_REPO / "configs/task_composition/quickstart.yaml"),
    "--data_dir",
    str(_REPO),
]


def _args(extra=()):
    return roi.build_parser().parse_args([*_BASE_ARGV, *extra])


def _call_windows(src: str) -> list[str]:
    """The text following every ``build_run_invariants(`` CALL (not the def)."""
    starts = [m.end() for m in re.finditer(r"build_run_invariants\(", src)]
    starts = [s for s in starts if "def build_run_invariants" not in src[s - 40 : s]]
    # Wide enough for the tuner's heavily-commented call (each site makes
    # exactly one call, so a window cannot bleed into a second one).
    return [src[s : s + 6000] for s in starts]


class TestLockSiteCensus:
    @pytest.mark.parametrize("site", sorted(LOCK_SITES))
    def test_every_lock_site_threads_all_three_identity_fields(self, site):
        """DECLARED DELTA (structural-budget closure at final integration):
        the four identity scalars became ONE typed ``LockLaunchIdentity``
        carrier — the 12a parameter budget fired on the 13→17 growth and the
        carrier is the §E.2 answer. The census keeps owning the SAME
        property, carrier-aware: every lock call must pass
        ``launch_identity=``, and the file's ``LockLaunchIdentity(``
        construction window must thread all four fields. HOW THIS FAILS:
        drop the carrier from a lock call → the first assertion names the
        site; drop one field from a site's constructor (or its extracted
        helper) → the second names the kwarg."""
        src = LOCK_SITES[site].read_text(encoding="utf-8")
        windows = _call_windows(src)
        assert windows, f"{site}: no build_run_invariants call found"
        for window in windows:
            assert "launch_identity=" in window, f"{site}: lock call missing launch_identity="
        ctor_windows = [
            src[m.end() : m.end() + 1200]
            for m in re.finditer(r"LockLaunchIdentity\(", src)
            if "class LockLaunchIdentity" not in src[m.start() - 60 : m.start()]
        ]
        assert ctor_windows, f"{site}: no LockLaunchIdentity construction found"
        for kwarg in IDENTITY_KWARGS:
            assert any(kwarg in w for w in ctor_windows), (
                f"{site}: no LockLaunchIdentity construction threads {kwarg}"
            )

    def test_exactly_three_production_callers(self):
        """A fourth production caller must join the audited identity surface."""
        expected = {p.resolve() for p in LOCK_SITES.values()}
        found: set[Path] = set()
        for top in (
            "agent",
            "core",
            "execute_tools",
            "nodes",
            "scripts",
            "workflows",
            "sdsc_submission_scripts",
            "tools",
            "dashboard",
            "ml_models",
        ):
            root = _REPO / top
            if not root.exists():
                continue
            for py in root.rglob("*.py"):
                if _call_windows(py.read_text(encoding="utf-8", errors="ignore")):
                    found.add(py.resolve())
        assert found == expected, sorted(str(p.relative_to(_REPO)) for p in found ^ expected)


class TestChainCli:
    def test_default_is_unlabelled(self):
        assert _args().experiment_arm is None

    def test_a_label_parses_verbatim(self):
        assert _args(["--experiment_arm", "with-prior-art"]).experiment_arm == "with-prior-art"

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_an_empty_label_is_an_argparse_error(self, bad):
        with pytest.raises(SystemExit) as exc:
            _args(["--experiment_arm", bad])
        assert exc.value.code != 0


class TestLaunchIdentityResolution:
    def _yaml(self, tmp_path, enabled: bool) -> Path:
        p = tmp_path / "lit_review_config.yaml"
        p.write_text(f"enabled: {'true' if enabled else 'false'}\nroot_papers: []\n")
        return p

    def test_cli_flag_wins_and_the_sha_is_the_resolved_file_bytes(self, tmp_path):
        cfg = self._yaml(tmp_path, enabled=False)
        identity = roi.resolve_launch_identity(
            _args(["--ml_lit_review_enabled", "--ml_lit_review_config", str(cfg)])
        )
        assert identity.lit_review_enabled is True
        assert identity.lit_review_config_sha256 == hashlib.sha256(cfg.read_bytes()).hexdigest()
        assert identity.lit_review_config_path == str(cfg)

    def test_the_yaml_drives_when_the_cli_is_silent(self, tmp_path):
        cfg = self._yaml(tmp_path, enabled=True)
        identity = roi.resolve_launch_identity(_args(["--ml_lit_review_config", str(cfg)]))
        assert identity.lit_review_enabled is True
        assert identity.lit_review_config_sha256 is not None

    def test_the_explicit_negative_flag_wins_over_an_enabled_yaml(self, tmp_path):
        """The OFF arm is expressed POSITIVELY on argv, and OFF carries no pin."""
        cfg = self._yaml(tmp_path, enabled=True)
        identity = roi.resolve_launch_identity(
            _args(["--no-ml_lit_review_enabled", "--ml_lit_review_config", str(cfg)])
        )
        assert identity.lit_review_enabled is False
        assert identity.lit_review_config_sha256 is None

    def test_a_missing_yaml_resolves_off_when_the_cli_is_silent(self, tmp_path):
        identity = roi.resolve_launch_identity(
            _args(["--ml_lit_review_config", str(tmp_path / "absent.yaml")])
        )
        assert identity.lit_review_enabled is False
        assert identity.lit_review_config_sha256 is None

    def test_enabled_with_an_unreadable_config_is_refused_before_launch(self, tmp_path):
        missing = tmp_path / "absent.yaml"
        with pytest.raises(ValueError, match=re.escape(str(missing))):
            roi.resolve_launch_identity(
                _args(["--ml_lit_review_enabled", "--ml_lit_review_config", str(missing)])
            )

    def test_compute_expected_invariants_carries_the_identity(self, tmp_path):
        from workflows.task_composition import (
            bind_run_task_composition,
            compose_run_task_bindings,
        )

        cfg = self._yaml(tmp_path, enabled=True)
        args = _args(["--experiment_arm", "with-prior-art", "--ml_lit_review_config", str(cfg)])
        args.workspace = str(tmp_path)
        args.health_gate_enabled = False  # avoid materializing gate config
        args.health_gate_files = None
        composition = compose_run_task_bindings(args.task_composition)
        with bind_run_task_composition(composition, physical_data_root=args.data_dir):
            explicit = roi.compute_expected_invariants(
                args,
                run_composition=composition,
                launch_identity=roi.resolve_launch_identity(args),
            )
            implicit = roi.compute_expected_invariants(args, run_composition=composition)
        assert explicit.experiment_arm == "with-prior-art"
        assert explicit.lit_review_enabled is True
        assert explicit.lit_review_config_sha256 == hashlib.sha256(cfg.read_bytes()).hexdigest()
        # A caller that predates the parameter resolves the SAME identity
        # through the same function — the two cannot diverge.
        assert implicit.canonical() == explicit.canonical()


def _identity(**overrides):
    base = dict(
        experiment_arm=None,
        lit_review_enabled=False,
        lit_review_config_path="configs/lit_review_config.yaml",
        lit_review_config_sha256=None,
    )
    base.update(overrides)
    return roi.LaunchIdentity(**base)


def _manifests(tmp_path, identity) -> dict[str, dict]:
    out = {}
    for name, kwargs in (
        ("no_records", {"results": []}),
        ("failed", {"results": [], "crashed": True}),
    ):
        iter_dir = tmp_path / name
        iter_dir.mkdir(parents=True)
        out[name] = roi.write_manifest(
            str(iter_dir), "iter_001", launch_identity=identity, **kwargs
        )
    return out


class TestManifestIdentityStamps:
    def test_a_labelled_lit_review_on_identity_is_stamped_on_every_branch(self, tmp_path):
        identity = _identity(
            experiment_arm="with-prior-art",
            lit_review_enabled=True,
            lit_review_config_sha256="a" * 64,
        )
        for name, manifest in _manifests(tmp_path, identity).items():
            assert manifest["experiment_arm"] == "with-prior-art", name
            assert manifest["lit_review_enabled"] is True, name
            assert manifest["lit_review_config_sha256"] == "a" * 64, name
            on_disk = json.loads((tmp_path / name / "manifest.json").read_text())
            assert on_disk["experiment_arm"] == "with-prior-art", name

    def test_the_without_arm_records_its_label_and_omits_the_off_topology(self, tmp_path):
        identity = _identity(experiment_arm="without-prior-art")
        for name, manifest in _manifests(tmp_path, identity).items():
            assert manifest["experiment_arm"] == "without-prior-art", name
            assert "lit_review_enabled" not in manifest, name
            assert "lit_review_config_sha256" not in manifest, name

    def test_an_unlabelled_off_identity_writes_no_key(self, tmp_path):
        """Key-for-key parity with a caller that predates the parameter."""
        with_identity = _manifests(tmp_path / "with", _identity())
        legacy = {}
        for name, kwargs in (
            ("no_records", {"results": []}),
            ("failed", {"results": [], "crashed": True}),
        ):
            iter_dir = tmp_path / "legacy" / name
            iter_dir.mkdir(parents=True)
            legacy[name] = roi.write_manifest(str(iter_dir), "iter_001", **kwargs)
        for name in with_identity:
            assert set(with_identity[name]) == set(legacy[name]), name
            for key in ("experiment_arm", "lit_review_enabled", "lit_review_config_sha256"):
                assert key not in with_identity[name], (name, key)


class TestMainWiring:
    def test_run_workflow_receives_the_identity_object_values(self):
        src = LOCK_SITES["chain"].read_text(encoding="utf-8")
        call = re.search(r"results = run_workflow\((.*?)\n            \)", src, re.DOTALL).group(1)
        assert "experiment_arm=launch_identity.experiment_arm" in call
        assert "lit_review_enabled=launch_identity.lit_review_enabled" in call
        assert "lit_review_config_path=launch_identity.lit_review_config_path" in call

    def test_every_manifest_written_by_main_carries_the_identity(self):
        """Every `write_manifest(` call in `main()` passes `launch_identity=`,
        except the ONE inside the identity-resolution failure handler, which
        by construction has nothing to pass. A new crash branch that forgets
        the identity would leave a labelled iteration unattributable exactly
        when it failed."""
        tree = ast.parse(LOCK_SITES["chain"].read_text(encoding="utf-8"))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls = [
            n
            for n in ast.walk(main)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "write_manifest"
        ]
        assert len(calls) >= 7, "main() lost manifest branches"
        missing = [c.lineno for c in calls if "launch_identity" not in {k.arg for k in c.keywords}]
        assert len(missing) == 1, f"manifest calls without launch_identity at lines {missing}"


def _shell(script_body: str) -> str:
    script = f"""
    set +e
    source "{_CHAIN_COMMON}"
    WORKSPACE=/tmp/ws
    RUN_NAME=cs
    SEED_PATHS=()
    {script_body}
    build_app_args 1
    printf '%s\\n' "${{APP_ARGS[@]}}"
    """
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


class TestShellForwarding:
    def test_unset_arm_emits_no_token(self):
        assert "--experiment_arm" not in _shell("").splitlines()

    def test_set_arm_is_forwarded_with_its_value(self):
        lines = _shell('EXPERIMENT_ARM="with-prior-art"').splitlines()
        i = lines.index("--experiment_arm")
        assert lines[i + 1] == "with-prior-art"

    def test_the_parser_accepts_the_chain_level_flag(self):
        lines = _shell("parse_chain_args --experiment_arm without-prior-art").splitlines()
        i = lines.index("--experiment_arm")
        assert lines[i + 1] == "without-prior-art"
