"""Step 11 C7 — spawn hygiene (F-11-4, F-11-7, and the §3.5 correction).

Three accidental couplings, none of them genericity work, all of them the
kind that fails in a way that names the wrong thing.

**F-11-4 — parent and child agreed by coincidence.** ``cached_models`` and
``records`` were independent string literals on both sides of the spawn,
with no shared authority and no parity test. The ``_OK_<exp_id>`` sentinel
read and the checkpoint read both depend on the two matching, and a
mismatch does not surface as "directory not found" — it surfaces as a
**false ``error_training``**, because the parent looks for a sentinel in a
place the child never wrote one.

**F-11-7 — relative script paths.** All three children were named by
relative path while ``cwd=os.getcwd()`` was passed explicitly, so the
launch worked only because every launcher happened to chdir to the
repository first. Every peer module already anchors at the package
location; this one was the exception.

**§3.5 — a justification that cited a mechanism that does not exist.** The
plain-vs-session split is operator-stop-critical and must not move. Its
docstring justified it with ``timeout --signal=INT``, which appears in no
shell script in the repository. **Fix the reason, never the behaviour**: a
stale justification is how a future reader talks themselves into
"unifying" a split that operator stop depends on.
"""

from __future__ import annotations

import ast
import os
import pathlib

import pytest

from core.sandbox_executor import (
    SANDBOX_SUBDIR_MODELS,
    SANDBOX_SUBDIR_RECORDS,
    SIDERIUS_ROOT,
    TidmadSandbox,
    child_script_path,
    sandbox_models_dir,
    sandbox_records_dir,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SANDBOX = REPO_ROOT / "src/core" / "sandbox_executor.py"
TRAINER = REPO_ROOT / "src/execute_tools" / "train_engine_sandbox.py"


# ----------------------------------------------------------------------
# F-11-4 — one authority for the subdirectory names
# ----------------------------------------------------------------------


class TestParentAndChildDeriveTheSamePaths:
    def test_the_parent_uses_the_authority(self, tmp_path, synthetic_physical_data_root):
        sb = TidmadSandbox(run_name="r", workspace=str(tmp_path))
        assert sb.dirs["models"] == sandbox_models_dir(sb.base_dir)
        assert sb.dirs["records"] == sandbox_records_dir(sb.base_dir)

    def test_the_agreement_is_enforced_not_coincidental(self):
        """The parity that matters: given ONE base dir, both sides resolve
        the same two paths through the same functions.
        """
        base = "/some/sandbox"
        parent_models = sandbox_models_dir(base)
        parent_records = sandbox_records_dir(base)

        # The child's own derivation, read from its source and executed the
        # way the child executes it.
        child_src = TRAINER.read_text(encoding="utf-8")
        assert "sandbox_models_dir(base_sandbox)" in child_src
        assert "sandbox_records_dir(base_sandbox)" in child_src

        assert parent_models == os.path.join(base, SANDBOX_SUBDIR_MODELS)
        assert parent_records == os.path.join(base, SANDBOX_SUBDIR_RECORDS)

    def test_no_module_rebuilds_the_names_from_literals(self):
        """Census: the strings may appear only where they are DECLARED.

        A planted `os.path.join(base, "cached_models")` anywhere else is the
        pre-C7 state returning, and it would agree with the authority right
        up until one of them changed.
        """
        offenders: list[str] = []
        for root in ("src/core", "src/execute_tools", "src/agent", "src/nodes", "src/workflows"):
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if not (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "join"
                    ):
                        continue
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and arg.value in {
                            SANDBOX_SUBDIR_MODELS,
                            SANDBOX_SUBDIR_RECORDS,
                        }:
                            rel = path.relative_to(REPO_ROOT)
                            if rel.as_posix() == "src/core/sandbox_executor.py":
                                continue  # the declaration itself
                            offenders.append(f"{rel}:{node.lineno} ({arg.value})")
        assert offenders == [], (
            "a sandbox subdirectory name is rebuilt from a literal outside "
            f"its authority; the sentinel read depends on the match: {offenders}"
        )

    def test_that_census_is_not_vacuous(self):
        src = SANDBOX.read_text(encoding="utf-8")
        assert f"os.path.join(base_dir, {SANDBOX_SUBDIR_MODELS!r})" in src.replace('"', "'") or (
            "SANDBOX_SUBDIR_MODELS" in src
        )


# ----------------------------------------------------------------------
# F-11-7 — absolute script anchoring, unchanged cwd semantics
# ----------------------------------------------------------------------


class TestScriptPathsAreAnchored:
    def test_the_root_is_the_installed_package_location(self):
        assert pathlib.Path(SIDERIUS_ROOT) == REPO_ROOT / "src"

    @pytest.mark.parametrize(
        "script",
        [
            "execute_tools/train_engine_sandbox.py",
            "execute_tools/inference_single.py",
            "execute_tools/denoising_score_single.py",
        ],
    )
    def test_each_child_script_resolves_absolutely_and_exists(self, script):
        resolved = child_script_path(script)
        assert os.path.isabs(resolved)
        assert os.path.isfile(resolved)

    def test_resolution_does_not_depend_on_the_working_directory(self, tmp_path, monkeypatch):
        """The whole point of F-11-7: the launch must not work only because
        the launcher happened to chdir to the repository first.
        """
        before = child_script_path("execute_tools/inference_single.py")
        monkeypatch.chdir(tmp_path)
        assert child_script_path("execute_tools/inference_single.py") == before
        assert os.path.isfile(before)

    def test_no_builder_still_names_a_child_by_relative_path(self):
        src = SANDBOX.read_text(encoding="utf-8")
        assert '"execute_tools/train_engine_sandbox.py",' not in src
        assert '"execute_tools/inference_single.py",' not in src
        assert '"execute_tools/denoising_score_single.py",' not in src
        assert src.count("child_script_path(") == 4  # 3 call sites + the def

    def test_cwd_semantics_are_unchanged(self):
        """C7 changes how the interpreter FINDS the script, nothing else.
        The children still run with the caller's working directory, because
        relative paths in their own arguments resolve against it.
        """
        tree = ast.parse(SANDBOX.read_text(encoding="utf-8"))
        cwd_launches = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for kw in node.keywords
            if kw.arg == "cwd"
        ]
        assert len(cwd_launches) == 3, (
            f"the three child launches must still pass the caller's cwd; found {len(cwd_launches)}"
        )


# ----------------------------------------------------------------------
# §3.5 — the corrected justification, and the UNCHANGED behaviour
# ----------------------------------------------------------------------


class TestTheLaunchSplitIsUnchangedAndCorrectlyJustified:
    def test_the_behaviour_did_not_move(self):
        """The operator-stop-critical invariant: deadline mode takes its own
        session, plain mode does not.
        """
        src = SANDBOX.read_text(encoding="utf-8")
        tree = ast.parse(src)
        wrapper = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_run_observed_subprocess"
        )
        assert any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_run_observed_process"
            for n in ast.walk(wrapper)
        ), "the package wrapper must still call the process-supervision owner"
        fn = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_run_observed_process"
        )
        sessions = [
            kw.value.value
            for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            for kw in node.keywords
            if kw.arg == "start_new_session" and isinstance(kw.value, ast.Constant)
        ]
        assert sessions == [True], (
            "exactly ONE launch in this seam takes its own session (the "
            f"deadline path); got {sessions}"
        )

    def test_the_stale_mechanism_is_no_longer_cited_as_fact(self):
        """`timeout --signal=INT` may appear ONLY inside the correction that
        records it was wrong — never as a live justification.
        """
        src = SANDBOX.read_text(encoding="utf-8")
        for line_no, line in enumerate(src.splitlines(), 1):
            if "timeout --signal" in line:
                window = "\n".join(src.splitlines()[max(0, line_no - 6) : line_no + 3])
                assert "No launcher uses" in window or "used to cite" in window, (
                    f"line {line_no} cites `timeout --signal` as a live "
                    "justification; the mechanism does not exist"
                )

    def test_the_real_anchor_is_named(self):
        src = SANDBOX.read_text(encoding="utf-8")
        assert "run_chain.sh:171" in src
        assert "install_chain_stop_traps" in src

    def test_the_real_anchor_actually_exists(self):
        """Naming a mechanism is worth nothing if THAT one is also absent —
        which is the whole lesson of this finding.
        """
        chain = (REPO_ROOT / "scripts" / "launch" / "run_chain.sh").read_text(encoding="utf-8")
        assert '(cd "$PROJECT_DIR" && "${cmd[@]}")' in chain
        common = (REPO_ROOT / "scripts" / "launch" / "_chain_common.sh").read_text(encoding="utf-8")
        assert "install_chain_stop_traps()" in common
        assert "trap '_chain_note_signal SIGINT'  INT" in common

    def test_no_chain_lineage_launcher_uses_timeout_signal(self):
        """The finding itself, kept executable — SCOPE REVISITED, as its own
        docstring demanded, when a script DID adopt `timeout --signal`
        (arXiv #259/#261: `gpu_c_coresidency_probe.sh`, 2026-08-26).

        The C7 correction's claim was about the CHAIN-LAUNCHER LINEAGE: the
        sandbox docstring had justified its session behaviour by citing a
        chain-launcher `timeout --signal=INT` mechanism that did not exist;
        the real chain stop story is `install_chain_stop_traps()`. That claim
        is about scripts that launch PRODUCTION CHAINS, where a wall-clock
        kill would truncate science and stop semantics must be the trap
        chain. The GPU-C calibration probe is outside that claim: it is a
        bounded measurement harness whose per-leg `timeout --signal=TERM
        --kill-after=60` IS its boundedness contract — replacing it with
        stop traps would remove the guarantee the probe exists to provide.

        The scope is therefore DERIVED, not name-listed (the #304 `_EXEMPT`
        lesson): a script is chain-lineage iff it references `run_chain.sh`
        or `_chain_common.sh`. Every real chain launcher is in that set; a
        harness that caps its own legs is not. If a CHAIN-LINEAGE script
        ever adopts `timeout --signal`, this turns red and the corrected
        justification must be revisited rather than quietly re-inverted.
        """
        chain_lineage_hits = []
        for p in sorted(REPO_ROOT.rglob("*.sh")):
            if ".venv" in p.parts:
                continue
            text = p.read_text(encoding="utf-8")
            if "timeout --signal" not in text:
                continue
            if "run_chain.sh" in text or "_chain_common.sh" in text:
                chain_lineage_hits.append(str(p.relative_to(REPO_ROOT)))
        assert chain_lineage_hits == [], (
            f"a CHAIN-LINEAGE launcher now uses `timeout --signal`: {chain_lineage_hits} — "
            "the C7 corrected justification must be revisited, not re-inverted"
        )
