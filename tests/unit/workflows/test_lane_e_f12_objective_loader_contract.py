"""Lane E / F12 — producer acceptance must imply consumer executability.

**The defect.** The manifest's ``objective:`` section and the loss registry
validated a plugin by different KINDS, so composition could select an
objective the registry would refuse to load:

* producer — ``_compose_objective`` resolved ONE symbol (the plugin's own
  ``PLUGIN_LOSS_TYPE``) and built a ``LossConfig`` from its value;
* consumer — ``_load_loss_plugin`` imports and requires THREE symbols,
  ``return None``-ing (skipping, never raising) on any miss.

A pack that adapted DAVIS's loss plugin and dropped the two class symbols
therefore composed successfully, the planner override fired
(``'focal'/None -> 'custom'/'waveform_exact_mse'``), and the run died much
later at admission with ``Custom loss ... not found in LOSS_REGISTRY``, whose
remediation text says *"run the implementor first to generate the loss
plugin"* — advice that is wrong for a declared, content-pinned pack plugin
that composition had already resolved. The ``[LossLoader] Skipping ...`` line
naming the true cause was printed during an unrelated earlier scan.

**The fix.** ``_load_symbol`` gained ``also_require``: companion symbols
checked on the module it JUST executed, so there is no second import and no
text heuristic. Producer and consumer now read ONE tuple,
``REQUIRED_LOSS_PLUGIN_SYMBOLS``.

**What is deliberately NOT changed.** Transport. ``active_run_loss_plugin_roots()``
already reaches the child via ``SIDERIUS_LOSS_DIRS``; the reporter's first
draft blamed transport and was wrong. No test here asserts anything about it.
"""

from __future__ import annotations

import pathlib
import shutil

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
DAVIS = str(REPO_ROOT / "configs" / "task_composition" / "davis.yaml")
DAVIS_OBJECTIVE = REPO_ROOT / "examples/davis_future_prediction/plugins/davis_exact_l1_loss.py"


def _production_python_files() -> list[pathlib.Path]:
    """Every production ``.py`` the contract census ranges over.

    ONE function, called by the census AND by the guard on the census. The
    first version had the guard rebuild its own ``REPO_ROOT.rglob(...)``, so
    narrowing the census to ``workflows/`` left all three tests GREEN — it
    pinned a COPY of the glob, not the glob. That is
    "a test that captures what production recomputes", one layer up: the
    guard held a duplicated expression where the thing under test computes
    its own.
    """
    out: list[pathlib.Path] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if {".venv", "tests", "__pycache__", "build", ".git"} & set(
            path.relative_to(REPO_ROOT).parts
        ):
            continue
        out.append(path)
    return out


#: The ONE file allowed to spell the names out: the tuple's own declaration.
DECLARATION_FILE = REPO_ROOT / "agent_generated" / "_loss_loader.py"


def _source_outside_the_declaration(path: pathlib.Path) -> str:
    """The source a hand-written copy could hide in.

    The exemption is a CONJUNCTION — this FILE **and** this STATEMENT — and
    both halves are load-bearing, because each one alone was shipped and each
    one alone had a hole:

    * exempting the FILE (first version) left the declaring file's own
      enforcement loop unguarded: a re-inlined literal inside
      ``_load_loss_plugin`` passed;
    * exempting the STATEMENT anywhere (second version) let a SECOND
      hand-written copy hide by wearing the declaration's NAME —
      ``REQUIRED_LOSS_PLUGIN_SYMBOLS = (...)`` in some other module is
      exactly the duplication this census exists to prevent, and cutting it
      as "the declaration" made it invisible.

    So: outside the declaring file nothing is cut at all, and inside it only
    the assignment statement is.
    """
    import ast

    src = path.read_text(encoding="utf-8", errors="ignore")
    if path != DECLARATION_FILE:
        return src
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if any(
            isinstance(tgt, ast.Name) and tgt.id == "REQUIRED_LOSS_PLUGIN_SYMBOLS"
            for tgt in targets
        ):
            segment = ast.get_source_segment(src, node)
            if segment:
                src = src.replace(segment, "")
    return src


def _scan_for_hand_written_triples() -> tuple[list[str], list[str]]:
    """Run the census. Returns ``(offenders, files_actually_scanned)``.

    ONE function performs the scan and reports BOTH results, so the range
    guard asserts on the list this loop really iterated. The previous version
    had the guard call ``_production_python_files()`` a second time, which
    detects a narrowed HELPER and not a narrowed CALL SITE — narrowing the
    census's own glob left the suite green.
    """
    offenders: list[str] = []
    scanned: list[str] = []
    for path in _production_python_files():
        rel = str(path.relative_to(REPO_ROOT))
        scanned.append(rel)
        text = _source_outside_the_declaration(path)
        if '"PLUGIN_LOSS_CONFIG_CLASS"' in text and '"PLUGIN_LOSS_CLASS"' in text:
            offenders.append(rel)
    return offenders, scanned


def _write_shadow_copy(directory: pathlib.Path) -> pathlib.Path:
    """Write a file that DECLARES the tuple's name AND hand-writes the triple.

    ``directory`` is supplied by the caller — pytest's ``tmp_path`` at every
    call site here. Nothing is written into the repository: the property
    under test is what ``_source_outside_the_declaration`` returns for a
    NON-CANONICAL path, which needs no repository write and no cleanup of
    its own.
    """
    target = directory / "_shadow_probe.py"
    target.write_text(
        'REQUIRED_LOSS_PLUGIN_SYMBOLS = ("PLUGIN_LOSS_TYPE", '
        '"PLUGIN_LOSS_CONFIG_CLASS", "PLUGIN_LOSS_CLASS")\n'
        "\n\ndef validate(module):\n"
        "    for attr in REQUIRED_LOSS_PLUGIN_SYMBOLS:\n"
        "        if not hasattr(module, attr):\n"
        "            return attr\n",
        encoding="utf-8",
    )
    return target


def _compose(manifest: str):
    from workflows.task_composition import compose_run_task_bindings

    return compose_run_task_bindings(manifest)


class TestOneAuthorityForTheAdmissionContract:
    """No enforcer of the loss-plugin admission contract may hold its own copy.

    The census below ranges over the WHOLE production tree, not over the two
    files this PR happened to edit. The first version read only
    ``_loss_loader.py`` and ``task_composition.py`` and was therefore
    structurally incapable of seeing the third copy a reviewer found in
    ``ml_model_implementor.py`` — the file-set omission mode, inside the very
    check written to prevent duplication.
    """

    def test_no_production_file_hand_writes_the_triple(self):
        """The whole tree, minus the one file allowed to spell it out.

        A hand-written copy reopens F12 one family over: add a fourth symbol,
        have the loader and the objective resolver require it, and any
        enforcer still checking its own three-item literal admits a plugin
        the registry will skip.
        """
        offenders, _scanned = _scan_for_hand_written_triples()
        assert not offenders, (
            "these enforce the loss-plugin contract from a hand-written copy "
            f"instead of importing REQUIRED_LOSS_PLUGIN_SYMBOLS: {offenders}"
        )

    def test_a_shadow_copy_cannot_hide_behind_the_declaration_name(self, tmp_path):
        """C2-c — the class under repair, appearing inside the repair.

        The statement-scoped exemption cut ANY module-level assignment to
        ``REQUIRED_LOSS_PLUGIN_SYMBOLS``, in any file. So a SECOND
        hand-written copy became invisible simply by wearing the
        declaration's name — and that is a plausible edit, not a contrived
        one: ``agent_generated/`` sits outside ruff and pyright, so a
        developer avoiding an import across that boundary writes exactly
        this, and it reads as correct.

        The file-scoped version caught it; fixing the file-scoping
        introduced its complement. The exemption is now the CONJUNCTION, and
        this asserts the half that regressed: outside the declaring file,
        NOTHING is cut.
        """
        shadow = _write_shadow_copy(tmp_path)
        assert '"PLUGIN_LOSS_CONFIG_CLASS"' in _source_outside_the_declaration(shadow)
        assert '"PLUGIN_LOSS_CLASS"' in _source_outside_the_declaration(shadow)

    def test_the_declaration_itself_is_still_exempt(self):
        """The other half of the conjunction. If this fails, the declaring
        file reports itself and the census is unusable."""
        cut = _source_outside_the_declaration(DECLARATION_FILE)
        assert '"PLUGIN_LOSS_CONFIG_CLASS"' not in cut
        assert "for attr in REQUIRED_LOSS_PLUGIN_SYMBOLS:" in cut, (
            "only the ASSIGNMENT may be cut — the enforcement loop must remain "
            "visible to the census"
        )

    def test_the_loader_enforces_through_the_shared_tuple(self):
        """RESTORED. This assertion existed at bbbc7dc7, caught exactly this,
        and my own C2 commit deleted it while claiming the census had it
        covered. It did not: the census exempted the loader's whole FILE.

        It is kept ALONGSIDE the census because the two fail on different
        edits. The census catches a re-inlined literal anywhere; this catches
        the loader replacing the loop with something that consults the tuple
        not at all — a check that imports the name and then ignores it.
        """
        from agent_generated import _loss_loader

        source = pathlib.Path(_loss_loader.__file__).read_text(encoding="utf-8")
        assert "for attr in REQUIRED_LOSS_PLUGIN_SYMBOLS:" in source, (
            "the PRIMARY CONSUMER must enforce through the shared tuple; a "
            "re-inlined literal triple here is the drift F12 is about"
        )

    def test_the_census_ranges_over_the_whole_tree(self):
        """A census whose file set is too narrow passes for the wrong reason.

        Asserts against the list the census loop ACTUALLY iterated, not
        against a second call to the file-list helper. That distinction is
        the whole point: a helper-level narrowing and a call-site-level
        narrowing both have to fail here, and only the former did while this
        rebuilt its own view.
        """
        _offenders, scanned = _scan_for_hand_written_triples()
        seen = set(scanned)
        for enforcer in (
            "agent_generated/_loss_loader.py",
            "workflows/task_composition.py",
            "nodes/ml_model_implementor/ml_model_implementor.py",
        ):
            assert enforcer in seen, f"the census cannot see {enforcer}"

    def test_every_enforcer_imports_the_shared_tuple(self):
        from agent_generated._loss_loader import REQUIRED_LOSS_PLUGIN_SYMBOLS

        for rel in (
            "agent_generated/_loss_loader.py",
            "workflows/task_composition.py",
            "nodes/ml_model_implementor/ml_model_implementor.py",
        ):
            source = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "REQUIRED_LOSS_PLUGIN_SYMBOLS" in source, rel

        assert REQUIRED_LOSS_PLUGIN_SYMBOLS == (
            "PLUGIN_LOSS_TYPE",
            "PLUGIN_LOSS_CONFIG_CLASS",
            "PLUGIN_LOSS_CLASS",
        )


class TestTheCheckStaysOnAModuleWeLoaded:
    """Supervisor ruling 2 — convert an incidental safety boundary into a
    stated one.

    ``_require_companion_symbols`` is safe ONLY because it runs inside
    ``_load_symbol``, on a module that function just executed. Lifted to a
    caller that has not loaded the module, the check would have to import to
    answer — which is precisely the unsafe side effect
    ``_objective_name_declared_by`` avoids by scanning text instead. These
    tests fail if a refactor moves it out.
    """

    def test_the_check_runs_only_where_the_module_was_just_produced(self):
        """The structural form of the boundary.

        Exactly one caller, and inside it the check sits in the SAME
        ``registration_rollback`` block as the ``exec_module`` that produces
        the module.

        Both halves matter. One caller alone would still allow the check to
        drift below the rollback — which is the C4 defect. Same-block alone
        would allow a second caller elsewhere to apply it to a module nobody
        here loaded, which is the unsafe-import hazard.
        """
        import ast

        source = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        def _calls(node, name):
            """Matches ``name(...)`` and ``a.b.name(...)`` alike.

            The attribute form matters: the call that produces the module is
            ``spec.loader.exec_module(module)``, and a Name-only matcher
            silently found nothing — a guard that passes because it cannot
            see its subject.
            """
            for n in ast.walk(node):
                if not isinstance(n, ast.Call):
                    continue
                func = n.func
                if isinstance(func, ast.Name) and func.id == name:
                    return True
                if isinstance(func, ast.Attribute) and func.attr == name:
                    return True
            return False

        callers = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and _calls(node, "_require_companion_symbols")
        }
        assert callers == {"_load_symbol"}, (
            "the companion check must run in exactly one place, on a module "
            f"produced in that same scope; found callers: {sorted(callers)}"
        )

        owner = next(
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_load_symbol"
        )
        guarded = [
            with_node
            for with_node in ast.walk(owner)
            if isinstance(with_node, ast.With)
            and any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == "registration_rollback"
                for item in with_node.items
            )
            and _calls(with_node, "_require_companion_symbols")
            and _calls(with_node, "exec_module")
        ]
        assert guarded, (
            "the check and the call that produces the module must share one "
            "registration_rollback block; a check outside it leaves the "
            "registry dirty when it refuses (C4)"
        )

    def test_the_text_scanning_sibling_never_gained_the_check(self):
        """``_objective_name_declared_by`` scans files the manifest never
        named. It must stay no-execute: no hasattr, no import."""
        import inspect

        from workflows import task_composition

        source = inspect.getsource(task_composition._objective_name_declared_by)
        assert "hasattr" not in source
        assert "import_module" not in source
        assert "exec_module" not in source
        assert "re.search" in source, "it must still answer by TEXT"

    def test_the_refusal_unwinds_the_import(self):
        """A refusal may not leave the process dirtier than it found it.

        Named for what it asserts: ``sys.modules``. It does NOT assert the
        REGISTRY half — that needs a plugin which registers and then fails,
        and the reviewer's anti-vacuity control covers it. Claiming the
        registry in the name while asserting only the import is the
        name-vs-assertion mismatch corrected two tests over.

        The check originally ran AFTER the ``registration_rollback`` block had
        committed and after the handler that pops ``sys.modules``, so a plugin
        that registered something and then failed left the registry dirty and
        its module importable — the F-12bc-2 class the surrounding code exists
        to prevent. Caught by review, not by any test, because nothing here
        looked at the process state after a refusal.
        """
        import sys

        from workflows.task_composition import TaskCompositionError

        before = set(sys.modules)
        source = DAVIS_OBJECTIVE.read_text(encoding="utf-8")
        try:
            DAVIS_OBJECTIVE.write_text(
                source.replace("PLUGIN_LOSS_CLASS =", "_DISABLED_PLUGIN_LOSS_CLASS ="),
                encoding="utf-8",
            )
            with pytest.raises(TaskCompositionError):
                _compose(DAVIS)
        finally:
            DAVIS_OBJECTIVE.write_text(source, encoding="utf-8")

        # Scoped to the module COMPOSITION created, by its own sys.modules
        # prefix. Two other things legitimately appear and are not this
        # defect: metric plugins that loaded successfully earlier in the same
        # composition (composition-wide unwinding is a different question),
        # and `siderius_plugin_davis_exact_l1_loss` — the MODEL plugin
        # scanner's copy, because DAVIS declares one `plugins/` directory and
        # that scanner loads every `.py` in it. Neither is created by the path
        # C4 is about, and asserting over them would fail for reasons this
        # test does not own.
        leaked = [
            name
            for name in set(sys.modules) - before
            if name.startswith("siderius_task_composition_plugin_") and "davis_exact_l1" in name
        ]
        assert not leaked, f"the refused objective plugin stayed importable: {leaked}"


class TestCompositionRefusesAnUnloadableObjective:
    """The witness. Each case removes a symbol the registry requires and
    asserts composition refuses AT STARTUP, naming it."""

    @pytest.mark.parametrize(
        "missing",
        ["PLUGIN_LOSS_CONFIG_CLASS", "PLUGIN_LOSS_CLASS"],
    )
    def test_a_declared_objective_missing_a_loader_symbol_is_refused(self, missing, tmp_path):
        """Reproduces F12's real trigger: the reporter adapted the DAVIS
        plugin and omitted the two class symbols.

        RED without the fix — composition returned a valid LossConfig and the
        run failed later, at admission, with misleading remediation text.
        """
        from workflows.task_composition import TaskCompositionError

        backup = tmp_path / "objective.bak"
        shutil.copy2(DAVIS_OBJECTIVE, backup)
        try:
            source = DAVIS_OBJECTIVE.read_text(encoding="utf-8")
            assert f"{missing} =" in source, "fixture assumption: the plugin declares it"
            # Neutralise the export while leaving the file importable, exactly
            # as an incomplete adaptation would.
            DAVIS_OBJECTIVE.write_text(
                source.replace(f"{missing} =", f"_DISABLED_{missing} ="), encoding="utf-8"
            )
            with pytest.raises(TaskCompositionError) as excinfo:
                _compose(DAVIS)
        finally:
            shutil.copy2(backup, DAVIS_OBJECTIVE)

        message = str(excinfo.value)
        assert missing in message, "the refusal must NAME the missing symbol"
        assert "loss registry SKIPS" in message, (
            "the refusal must state the CONSUMER's rule — 'PLUGIN_LOSS_TYPE "
            "resolved fine' is what made the later skip inexplicable"
        )
        assert "run the implementor" not in message.lower(), (
            "must NOT repeat the generated-plugin remediation that misled the "
            "reporter; this is a declared, content-pinned pack plugin"
        )

    def test_every_missing_symbol_is_named_at_once(self, tmp_path):
        """A pack adapting another pack typically drops the companion PAIR.
        Naming one at a time turns one edit into two failed launches."""
        from workflows.task_composition import TaskCompositionError

        backup = tmp_path / "objective.bak"
        shutil.copy2(DAVIS_OBJECTIVE, backup)
        try:
            source = DAVIS_OBJECTIVE.read_text(encoding="utf-8")
            for name in ("PLUGIN_LOSS_CONFIG_CLASS", "PLUGIN_LOSS_CLASS"):
                source = source.replace(f"{name} =", f"_DISABLED_{name} =")
            DAVIS_OBJECTIVE.write_text(source, encoding="utf-8")
            with pytest.raises(TaskCompositionError) as excinfo:
                _compose(DAVIS)
        finally:
            shutil.copy2(backup, DAVIS_OBJECTIVE)

        message = str(excinfo.value)
        assert "PLUGIN_LOSS_CONFIG_CLASS" in message
        assert "PLUGIN_LOSS_CLASS" in message

    def test_the_shipped_plugin_still_composes_after_the_mutations(self):
        """The mutation tests above edit a REAL shipped plugin. If a restore
        ever leaks, every later assertion in the suite is meaningless.

        Named for what it asserts: the pristine file COMPOSES. It does not
        compare bytes, so it would not catch a restore that changed
        whitespace — the byte-level guarantee is the ``shutil.copy2`` of an
        untouched backup, not this."""
        assert _compose(DAVIS).objective is not None

    def test_the_declared_objective_actually_loads_through_the_consumer(self):
        """The behavioural half of "acceptance implies executability".

        Every other test here asserts a REFUSAL. Nothing asserted the
        positive: that a plugin the producer accepts is one the CONSUMER can
        actually load and register. Without this, a change that made the
        producer stricter than the loader would pass the whole suite.
        """
        from agent_generated._loss_loader import _load_loss_plugin

        composed = _compose(DAVIS)
        loaded = _load_loss_plugin(str(DAVIS_OBJECTIVE))

        assert loaded is not None, "the consumer skipped a plugin the producer accepted"
        assert loaded["loss_type"] == composed.objective.loss_name


class TestTheUnaffectedPathsStayUnaffected:
    """``also_require`` defaults to empty, so nothing else may move."""

    def test_a_complete_objective_still_composes(self):
        composed = _compose(DAVIS)
        assert composed.objective is not None
        assert composed.objective.loss_type == "custom"

    @pytest.mark.parametrize("manifest", ["tidmad.yaml", "pets.yaml"])
    def test_manifests_declaring_no_objective_are_untouched(self, manifest):
        composed = _compose(str(REPO_ROOT / "configs" / "task_composition" / manifest))
        assert composed.objective is None

    def test_non_loss_families_do_not_acquire_the_loss_contract(self):
        """The metric and data-path resolvers must NOT start requiring loss
        symbols — ``also_require`` is opt-in per call site, and a blanket
        application would refuse every metric plugin in the repository."""
        source = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        assert source.count("also_require=REQUIRED_LOSS_PLUGIN_SYMBOLS") == 1, (
            "exactly ONE call site — the objective resolver — may require the loss-plugin triple"
        )
