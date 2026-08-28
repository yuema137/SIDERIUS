"""Gold campaign — the advice identity that reaches the lock is OBSERVED.

The trap this module exists for: certification SUCCEEDS only when the
declared and the observed digest are equal, so a lock stamped with the
DECLARED value is behaviourally indistinguishable from one stamped with
the observed value — right up until the day the two differ, which is
exactly the day the record has to be true. No behavioural test can see
that; #346 hit the same trap one subsystem over and answered it with an
AST guard, which is the precedent followed here.

What only these tests catch:

* ``TestTheStampIsObservedNotDeclared`` — the echo. ``args.advice_sha256``
  is the DECLARED value and may reach exactly one place: the
  ``declared_sha256=`` parameter of the artifact loader. A future edit that
  hands it to ``LaunchIdentity`` or ``LockLaunchIdentity`` instead makes the
  lock a mirror of its own argv.
* ``TestOneReadHashedAndParsed`` — the TOCTOU window: hash-then-reopen means
  a swapped file is hashed as one content and parsed as another, so the
  advice INJECTED into the proposer and the advice PINNED in the lock would
  describe different bytes. Nothing races in-process, so every behavioural
  test stays green.
* ``TestOneAuthority`` — a second reader with its own ``open()`` reproduces
  the same divergence without a second read appearing inside the loader.
* ``TestLockSitePosture`` — the two sites that lock the CHAIN workspace
  thread the pin; the tuner sub-lock and the baseline lock deliberately do
  not. Pinning the whole posture is what makes a half-threaded fifth caller
  visible, and what stops the deliberate omissions being rediscovered as
  bugs.
* ``TestShellTransport`` — the digest crosses ``_chain_common.sh``, and an
  undeclared chain's argv is byte-identical to a pre-feature run.
* ``TestChildRefusals`` — missing artifact, unparseable artifact, and a
  declared digest that does not match: each refuses the launch rather than
  running an untreated arm under a treated label.
* ``TestConsumabilityRefusals`` (F-SCHED-5) — the artifact is the one the
  launcher bound AND it can inject. Every test above certifies WHICH bytes
  were read; none of them asks whether those bytes reach a prompt, and the
  binding mechanism working perfectly is what hides the difference.
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

_ROI_PATH = _REPO / "sdsc_submission_scripts" / "run_one_iteration.py"
_CHAIN_COMMON = _REPO / "sdsc_submission_scripts" / "_chain_common.sh"

_spec = importlib.util.spec_from_file_location("run_one_iteration_for_advice_test", _ROI_PATH)
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)

_BASE_ARGV = ["--workspace", "/tmp/ws", "--start_iteration", "1", "--run_name", "t"]


def _args(extra=()):
    return roi.build_parser().parse_args([*_BASE_ARGV, *extra])


def _advice(tmp_path, name="advice.json", body=None):
    p = tmp_path / name
    p.write_text(json.dumps(body if body is not None else {"propose": "P", "tune": "T"}))
    return p, hashlib.sha256(p.read_bytes()).hexdigest()


def _roi_tree() -> ast.AST:
    """The production source, located through the imported module's file —
    never a hardcoded path (repository-portability rule)."""
    assert roi.__file__ is not None
    return ast.parse(Path(roi.__file__).read_text(encoding="utf-8"), filename=roi.__file__)


# ---------------------------------------------------------------------------
# The echo
# ---------------------------------------------------------------------------


class TestTheStampIsObservedNotDeclared:
    def test_the_declared_digest_reaches_only_the_certification_parameter(self):
        """``args.advice_sha256`` is what the LAUNCHER said. It may be read
        exactly once, to be certified against this process's own read, and
        then it is discarded.

        HOW THIS FAILS: pass it to ``LaunchIdentity(advice_sha256=...)``,
        to ``LockLaunchIdentity(...)``, or assign it onto the artifact —
        the count goes above one and the test names the line. Every
        behavioural test in the repository stays green through that edit,
        because the two values are equal in every scenario anyone writes
        down; they differ only when the file on the pod is not the file the
        launcher hashed, which is the single case the pin exists for."""
        tree = _roi_tree()
        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "advice_sha256"
            and isinstance(node.value, ast.Name)
            and node.value.id == "args"
        ]
        assert len(reads) == 1, (
            "the DECLARED advice digest is read at lines "
            f"{[n.lineno for n in reads]}; it may be read exactly once, as the "
            "value certified against this process's own observation. A second "
            "read is how the lock becomes an echo of its own argv."
        )
        declared_kwargs = [
            keyword
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "declared_sha256"
        ]
        assert any(keyword.value is reads[0] for keyword in declared_kwargs), (
            "the single read of args.advice_sha256 must be the "
            "declared_sha256= argument of the artifact loader; it is "
            f"currently used at line {reads[0].lineno} for something else."
        )

    def test_the_launch_identity_takes_the_artifacts_own_digest(self):
        """``LaunchIdentity`` is what the pre-flight lock and the workflow
        launch config both read, so it is the last place the observed value
        can be swapped for the declared one.

        HOW THIS FAILS: change either construction argument to anything not
        rooted in the loaded artifact and the assertion names the kwarg."""
        src = Path(roi.__file__).read_text(encoding="utf-8")
        window = re.search(r"return LaunchIdentity\((.*?)\n    \)", src, re.DOTALL)
        assert window is not None, "resolve_launch_identity's construction was not found"
        body = window.group(1)
        assert "advice_sha256=None if advice is None else advice.sha256" in body
        assert "advice_path=None if advice is None else advice.path" in body

    def test_the_observed_digest_is_what_lands_in_the_identity(self, tmp_path):
        """The behavioural half, for the case the two values AGREE: even
        then the identity must equal a digest computed here, over the file's
        real bytes — not merely equal to whatever was declared.

        HOW THIS FAILS: stamp the declaration and this still passes; that is
        why the AST witness above is a separate, independent case."""
        path, sha = _advice(tmp_path)
        identity = roi.resolve_launch_identity(
            roi.normalize_args(_args(["--advice", str(path), "--advice_sha256", sha]))
        )
        assert identity.advice_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert identity.advice_path == str(path)


# ---------------------------------------------------------------------------
# One read, hashed and parsed
# ---------------------------------------------------------------------------


class TestOneReadHashedAndParsed:
    def test_the_loader_hashes_the_exact_bytes_it_parses(self):
        """HOW THIS FAILS: rewrite ``load_advice_artifact`` to verify the
        digest and then ``open()`` the file again to parse it. Between the
        two reads a swapped file is hashed as one content and parsed as
        another — the advice the proposer receives and the advice the lock
        pins would describe different bytes, and every behavioural test
        stays green because nothing races in-process."""
        loader = next(
            node
            for node in ast.walk(_roi_tree())
            if isinstance(node, ast.FunctionDef) and node.name == "load_advice_artifact"
        )
        read_bytes_calls = 0
        forbidden: list[str] = []
        sha_args: list[str] = []
        loads_args: list[str] = []
        for node in ast.walk(loader):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                forbidden.append("open")
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr == "read_bytes":
                read_bytes_calls += 1
            elif func.attr in {"read_text", "open"}:
                forbidden.append(func.attr)
            elif (
                func.attr == "sha256"
                and isinstance(func.value, ast.Name)
                and func.value.id == "hashlib"
            ):
                first = node.args[0] if node.args else None
                assert isinstance(first, ast.Name), "hashlib.sha256 must hash a NAMED bytes object"
                sha_args.append(first.id)
            elif (
                func.attr == "loads"
                and isinstance(func.value, ast.Name)
                and func.value.id == "json"
            ):
                first = node.args[0] if node.args else None
                assert isinstance(first, ast.Name), "json.loads must parse a NAMED bytes object"
                loads_args.append(first.id)
        assert read_bytes_calls == 1, "the advice loader must read the file EXACTLY once"
        assert forbidden == [], f"re-open/second-read in the advice loader: {forbidden}"
        assert len(sha_args) == 1 and len(loads_args) == 1
        assert sha_args == loads_args, (
            f"json.loads must parse the SAME bytes object hashlib.sha256 hashed; "
            f"got sha256({sha_args[0]}) vs json.loads({loads_args[0]})"
        )


class TestOneAuthority:
    def test_nothing_else_opens_the_advice_file(self):
        """``resolve_advice_artifact`` is the one authority and caches on
        ``args``, so the advice CONTENT and the pinned IDENTITY come from
        one read.

        HOW THIS FAILS: restore the old ``open(advice_path)`` in
        ``normalize_args`` (or add any second reader) and the content the
        proposer receives can diverge from the identity the lock pins —
        without a second read ever appearing inside the loader, so the
        structural witness above would not fire."""
        tree = _roi_tree()
        callers = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "resolve_advice_artifact"
        ]
        assert len(callers) == 2, (
            f"expected exactly two consumers of the advice authority "
            f"(normalize_args for CONTENT, resolve_launch_identity for "
            f"IDENTITY); found calls at {callers}"
        )
        loaders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "load_advice_artifact"
        ]
        assert len(loaders) == 1, (
            f"load_advice_artifact must be called only by the caching authority; "
            f"found calls at {loaders}"
        )

    def test_the_content_and_the_identity_come_from_one_read(self, tmp_path):
        """The behavioural counterpart. HOW THIS FAILS: any divergence
        between what ``normalize_args`` exploded onto ``args`` and what the
        identity pinned."""
        path, sha = _advice(tmp_path, body={"propose": "PROPOSE", "mindset": "MIND"})
        args = roi.normalize_args(_args(["--advice", str(path)]))
        identity = roi.resolve_launch_identity(args)
        assert args.human_advice_propose == "PROPOSE"
        assert args.human_advice_mindset == "MIND"
        assert identity.advice_sha256 == sha


# ---------------------------------------------------------------------------
# Which locks carry the pin
# ---------------------------------------------------------------------------

_CHAIN_WORKSPACE_SITES = {
    "chain-preflight": _REPO / "sdsc_submission_scripts/run_one_iteration.py",
    "workflow": _REPO / "workflows/model_exploration.py",
}
_UNPINNED_SITES = {
    "tuner-sub-workspace": (
        _REPO / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
    ),
    "baseline": _REPO / "scripts/run_comparison.py",
}


def _lock_identity_windows(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    return [
        src[m.end() : m.end() + 1600]
        for m in re.finditer(r"LockLaunchIdentity\(", src)
        if "class LockLaunchIdentity" not in src[max(0, m.start() - 60) : m.start()]
    ]


class TestLockSitePosture:
    @pytest.mark.parametrize("site", sorted(_CHAIN_WORKSPACE_SITES))
    def test_both_chain_workspace_locks_thread_the_pin(self, site):
        """The pre-flight and ``run_workflow`` lock the SAME directory.

        HOW THIS FAILS: thread the pin at one and not the other, and the two
        write contradictory locks — the first wins, the second raises, and
        EVERY advice-bound run aborts at startup. This is the PR 2
        lock-collision failure mode, and it is why the census is per-site
        rather than a single "somebody threads it" assertion."""
        windows = _lock_identity_windows(_CHAIN_WORKSPACE_SITES[site])
        assert windows, f"{site}: no LockLaunchIdentity construction found"
        for kwarg in ("advice_sha256=", "advice_path="):
            assert any(kwarg in w for w in windows), f"{site}: no construction threads {kwarg}"

    @pytest.mark.parametrize("site", sorted(_UNPINNED_SITES))
    def test_the_other_two_locks_stay_deliberately_unpinned(self, site):
        """A PINNED POSTURE, not an oversight. The tuner locks a per-model
        SUB-workspace and ``run_comparison`` locks the baseline workspace;
        neither is the chain workspace the pre-flight validates first, so a
        divergent advice identity refuses before either is reached.
        Threading it further needs the tuner input schema and the
        ml_model_valid -> ml_model_tune protocol.

        HOW THIS FAILS: a future edit adds ``advice_sha256=`` at one of
        these without the schema work — producing a value that is always
        ``None`` for a real campaign and a lock that claims the run was
        untreated. The census names the site, and changing this test is the
        deliberate act of taking that decision."""
        src = _UNPINNED_SITES[site].read_text(encoding="utf-8")
        assert "advice_sha256" not in src, f"{site} threads advice_sha256 unexpectedly"
        assert "advice_path" not in src, f"{site} threads advice_path unexpectedly"


# ---------------------------------------------------------------------------
# The shell hop
# ---------------------------------------------------------------------------


def _app_args(script_body: str) -> list[str]:
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
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


class TestShellTransport:
    def test_a_declared_digest_reaches_the_child(self):
        """HOW THIS FAILS: parse the flag without forwarding it (or the
        reverse) and the campaign's cross-band certification never runs —
        the child pins whatever it finds and reports success."""
        lines = _app_args(f"parse_chain_args --advice /tmp/a.json --advice_sha256 {'a' * 64}")
        i = lines.index("--advice_sha256")
        assert lines[i + 1] == "a" * 64

    def test_a_digest_declared_for_the_legacy_advice_flag_also_reaches_the_child(self):
        """``--human_advice_file`` names an advice artifact too.

        HOW THIS FAILS: nest the emission inside the ``--advice`` branch and
        a legacy-flag launch silently loses its certification."""
        lines = _app_args(
            f"parse_chain_args --human_advice_file /tmp/a.json --advice_sha256 {'b' * 64}"
        )
        assert "--advice_sha256" in lines

    def test_an_undeclared_chain_emits_no_token(self):
        """The differential: a chain that declares no digest produces argv
        byte-identical to a pre-feature run.

        HOW THIS FAILS: emit the flag unconditionally (with an empty value,
        or a computed default) and every non-campaign launcher's child argv
        changes — including the v18/v19 queue runners."""
        assert "--advice_sha256" not in _app_args("parse_chain_args --advice /tmp/a.json")
        assert "--advice_sha256" not in _app_args("")


# ---------------------------------------------------------------------------
# The child's refusals
# ---------------------------------------------------------------------------


class TestChildRefusals:
    def test_a_declared_digest_that_does_not_match_refuses(self, tmp_path):
        """The FOUR-BAND property at the child boundary: the bands fork
        minutes apart into SEPARATE workspaces, so an edit to the artifact
        between two band launches produces two identities that no
        per-workspace lock can ever compare. Certifying each band against
        the one launcher-computed declaration is what catches it.

        HOW THIS FAILS: accept the declaration as advisory (warn and
        continue) and band 15-19 runs a different treatment from band 0-3
        while both report the same arm."""
        path, _sha = _advice(tmp_path)
        with pytest.raises(roi.AdviceArtifactError, match="cannot be certified"):
            roi.normalize_args(_args(["--advice", str(path), "--advice_sha256", "c" * 64]))

    def test_an_edit_after_the_declaration_is_caught(self, tmp_path):
        """The same property, driven by the real event rather than a wrong
        constant: hash the file, edit it, then launch with the earlier
        digest."""
        path, sha = _advice(tmp_path)
        path.write_text(json.dumps({"propose": "EDITED AFTER THE LAUNCHER HASHED IT"}))
        with pytest.raises(roi.AdviceArtifactError, match=re.escape(sha)):
            roi.normalize_args(_args(["--advice", str(path), "--advice_sha256", sha]))

    def test_a_missing_artifact_refuses(self, tmp_path):
        """HOW THIS FAILS: fall through to "no advice" and the run executes
        an untreated arm while carrying the treated arm's label."""
        with pytest.raises(roi.AdviceArtifactError, match="not found"):
            roi.normalize_args(_args(["--advice", str(tmp_path / "absent.json")]))

    def test_an_unparseable_artifact_refuses_and_names_its_digest(self, tmp_path):
        """HOW THIS FAILS: let the JSON error escape untyped and the
        operator gets a traceback with no way to tell WHICH bytes failed."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        with pytest.raises(roi.AdviceArtifactError, match="not valid JSON"):
            roi.normalize_args(_args(["--advice", str(bad)]))

    def test_a_run_without_advice_is_unchanged(self, tmp_path):
        """The differential at the child: no advice declared, nothing
        pinned, no refusal, and the advice fields resolve exactly as they
        did before the feature."""
        args = roi.normalize_args(_args())
        identity = roi.resolve_launch_identity(args)
        assert identity.advice_sha256 is None
        assert identity.advice_path is None
        assert args.human_advice_propose is None
        assert args.human_advice_mindset is None


# ---------------------------------------------------------------------------
# The child's refusals — CONSUMABILITY (F-SCHED-5)
# ---------------------------------------------------------------------------


class TestConsumabilityRefusals:
    """Certifying WHICH bytes were read says nothing about whether those
    bytes reach a prompt, and the binding mechanism is what hides the gap:
    a misspelled or empty artifact parses, hashes, is distributed to all
    four bands, is certified by each against the parent-pinned digest, and
    is pinned into the run-invariants lock — injecting nothing. Every test
    above stays green through that, because none of them asks the question.
    """

    def test_an_artifact_that_can_inject_nothing_refuses(self, tmp_path):
        """F-SCHED-5, the headline case: a JSON object whose every key is a
        MISSPELLING loads, hashes, is distributed to all four bands, is
        certified by each against the parent-pinned digest and is pinned into
        the run-invariants lock — while injecting nothing. Provenance then
        records that this artifact was the run's treatment, and every agent
        received nothing derived from it.

        HOW THIS FAILS: delete ``_validate_advice_consumability``'s call from
        the loader and this artifact loads clean. Nothing else in this
        module fires, because every other test here certifies WHICH bytes
        were read and this artifact's bytes are exactly the declared ones —
        the certification is not wrong, it is answering a different
        question."""
        path, sha = _advice(tmp_path, body={"implemnt": "IMPLEMENT, misspelled", "propse": "P"})
        with pytest.raises(roi.AdviceArtifactError) as excinfo:
            roi.normalize_args(_args(["--advice", str(path), "--advice_sha256", sha]))
        message = str(excinfo.value)
        assert "no agent reads" in message
        # The operator must be told WHICH keys, or the refusal is a puzzle.
        assert "'implemnt'" in message and "'propse'" in message

    def test_an_artifact_with_no_recognised_key_at_all_refuses(self, tmp_path):
        """The vacuous treatment in its purest form — an empty object, and an
        object carrying only a deliberately-inert annotation block. Both
        would pin a real digest and inject nothing.

        HOW THIS FAILS: implement the misspelling refusal alone. ``{}`` has
        no unrecognised key to catch, so it sails through a check written
        only against typos and the campaign's independent variable is set to
        nothing by an artifact that is not even malformed."""
        for body in ({}, {"_meta": {"purpose": "notes only"}}):
            path, _sha = _advice(tmp_path, body=body)
            with pytest.raises(roi.AdviceArtifactError, match="no recognised advice key"):
                roi.normalize_args(_args(["--advice", str(path)]))

    def test_a_declared_key_that_renders_empty_refuses(self, tmp_path):
        """The PARTIAL disappearance, which the whole-artifact non-vacuity
        rule cannot see: ``propose`` carries content, so "something arrives"
        is satisfied, while ``tune`` and ``implement`` are present in the
        artifact and absent from every prompt. The operator wrote three
        declarations and the run consumes one.

        The ``["", ""]`` case is the one a truthiness test cannot see at
        all: it joins to ``"\\n"``, which is TRUTHY, so ``or None`` keeps it
        and injects a bare newline as the treatment for that agent.
        Emptiness must be judged on the STRIPPED rendered text.

        HOW THIS FAILS: check only that SOME recognised key resolves
        non-empty (the pre-launch validator's rule 6) and this artifact
        passes. ``advice.get(key) or None`` drops the empty string silently,
        and keeps the whitespace-only line-list while it means nothing."""
        path, _sha = _advice(
            tmp_path,
            body={"propose": "REAL", "tune": "", "implement": ["", ""], "validate": []},
        )
        with pytest.raises(roi.AdviceArtifactError) as excinfo:
            roi.normalize_args(_args(["--advice", str(path)]))
        message = str(excinfo.value)
        assert "empty content" in message
        for key in ("'tune'", "'implement'", "'validate'"):
            assert key in message, f"{key} was declared, injects nothing, and was not named"

    def test_sparse_advice_stays_legal(self, tmp_path):
        """The over-refusal guard, and the boundary of this repair. The
        consumer reads every key independently and its own comment names
        TWO accepted shapes (4-key and 5-key); no campaign authority
        requires all six. An artifact carrying only ``propose`` — or only
        ``tune``, the shape ``advice/workflow/tidmad_collapse_advice.json``
        ships — is a legal treatment and must remain one.

        HOW THIS FAILS: implement the non-vacuity rule as "every recognised
        key must be present". Every refusal test above stays green, the
        corpus test goes red for a different reason, and a legitimate sparse
        treatment becomes a launch refusal — an integrity repair turned into
        a scientific-treatment change."""
        for index, (key, value) in enumerate([("propose", "P"), ("tune", "T"), ("mindset", "M")]):
            path, sha = _advice(tmp_path, name=f"sparse_{index}.json", body={key: value})
            args = roi.normalize_args(_args(["--advice", str(path), "--advice_sha256", sha]))
            assert getattr(args, f"human_advice_{key}") == value

    def test_a_recognised_key_that_is_not_text_refuses(self, tmp_path):
        """Advice is text an agent reads. A mapping reaches a prompt as a
        repr; a list holding a non-string reaches ``normalize_args``'s
        unguarded ``"\\n".join`` and raises a bare ``TypeError`` naming
        neither the file nor the key.

        HOW THIS FAILS: validate emptiness only. ``{"propose": {"a": 1}}``
        is truthy, so it passes an emptiness test and injects a Python repr
        of a dict as the campaign's treatment."""
        for body in ({"propose": {"a": 1}}, {"propose": ["ok", 7]}):
            path, _sha = _advice(tmp_path, body=body)
            with pytest.raises(roi.AdviceArtifactError, match="neither a string nor a list"):
                roi.normalize_args(_args(["--advice", str(path)]))

    def test_a_good_artifact_keeps_its_identity_and_still_injects(self, tmp_path):
        """The other direction, and the one that makes the refusals safe to
        ship: a valid artifact loads, renders its line-lists, reaches
        ``args.human_advice_*`` and pins the SAME digest it pinned before
        the refusals existed. The fix must not move the identity of a good
        artifact — every band certifies against a launcher-computed value,
        so a loader that perturbed the digest would refuse the whole fleet.

        HOW THIS FAILS: any refusal written too broadly (rejecting the
        ``_``-prefixed annotation block that ``gate2_smoke_advice.json``
        ships, or the list-of-lines form every ``advice/workflow`` artifact
        uses) turns a shipped artifact into a launch refusal."""
        body = {
            "_meta": {"purpose": "inert annotation, the gate2_smoke_advice.json convention"},
            "propose": ["line one", "line two"],
            "mindset": "MIND",
        }
        path, sha = _advice(tmp_path, body=body)
        args = roi.normalize_args(_args(["--advice", str(path), "--advice_sha256", sha]))
        identity = roi.resolve_launch_identity(args)
        # Identity: the digest is the file's, unchanged by validation.
        assert identity.advice_sha256 == hashlib.sha256(path.read_bytes()).hexdigest() == sha
        # Injection: the treatment actually reaches the agents.
        assert args.human_advice_propose == "line one\nline two"
        assert args.human_advice_mindset == "MIND"

    def test_every_committed_advice_artifact_still_loads(self):
        """The corpus, as the blast radius of the refusals. Each of these is
        an operator-authored artifact a Gate or a campaign may launch with,
        and a refusal written one notch too broad turns a shipped file into
        a launch failure discovered at fork time.

        HOW THIS FAILS: drop the ``_``-prefixed inert-key exemption and
        ``advice/workflow/gate2_smoke_advice.json`` (whose ``_meta`` block
        records why that artifact exists) refuses. No other test in the
        repository loads that file — which is how its ``_meta`` key survived
        unnoticed since 2026-07."""
        artifacts = sorted((_REPO / "advice").rglob("*.json"))
        assert artifacts, "no committed advice artifacts found; the corpus guard is vacuous"
        refused = {}
        for artifact in artifacts:
            try:
                loaded = roi.load_advice_artifact(str(artifact))
            except roi.AdviceArtifactError as exc:
                refused[artifact.name] = str(exc)
                continue
            # The digest is the file's own bytes, unmoved by validation.
            assert loaded.sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert not refused, f"committed advice artifacts refused by the loader: {refused}"

    def test_the_loader_and_the_consumer_share_one_rendering_rule(self, tmp_path):
        """The loader decides a key "carries content"; ``normalize_args``
        produces that content. Two spellings of one rule is how a key the
        loader accepted gets dropped anyway — the exact failure being fixed,
        reintroduced one layer down.

        HOW THIS FAILS: re-inline ``"\\n".join(v) if isinstance(v, list)``
        in ``normalize_args``. Behaviour agrees today, so no other test
        moves; it diverges the moment either rule is edited alone."""
        tree = _roi_tree()
        joins = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and isinstance(node.func.value, ast.Constant)
            and node.func.value.value == "\n"
        ]
        assert len(joins) == 1, (
            f"the advice line-list join must have exactly one authority "
            f"(render_advice_value); found joins at {joins}"
        )
        renderer = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "render_advice_value"
        )
        assert renderer.lineno < joins[0] < renderer.end_lineno, (
            "the one newline join must live inside render_advice_value"
        )

    def test_a_run_without_advice_is_unchanged(self, tmp_path):
        """The differential at the child: no advice declared, nothing
        pinned, no refusal, and the advice fields resolve exactly as they
        did before the feature."""
        args = roi.normalize_args(_args())
        identity = roi.resolve_launch_identity(args)
        assert identity.advice_sha256 is None
        assert identity.advice_path is None
        assert args.human_advice_propose is None
        assert args.human_advice_mindset is None
