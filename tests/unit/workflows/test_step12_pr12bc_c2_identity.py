"""Step 12 / PR-12bc — C2: parent-pinned identity, verified before consumption.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §E.2, §M / C2; ledger §Q.C2
(D-BC-5).

The frozen parent §7 invariant, made executable::

    Every child-consumed external semantic MUST be validated against an
    identity pinned by the parent BEFORE the child consumes it; a registry
    hit is never sufficient evidence of identity.

The second clause is the sharp one, and it is why verification is a separate
step rather than something folded into resolution. Resolution answers *"is
something registered under this name?"* — and a stale registration answers YES
while running different code. Identity answers *"is it the same code?"*.

**D-BC-5 = per-family content identity, not the composition fingerprint.** The
fingerprint is both too broad (a training child would refuse because an
unrelated `interpretation_blocks` sentence changed) and too vague (it can say
only "the composition differs", never WHICH thing did). See §Q.C2.
"""

from __future__ import annotations

import ast
import pathlib
import textwrap

import pytest

# The built-ins' bootstrap, performed at COLLECTION time — deliberately, and
# not for tidiness. These modules register their implementations as an import
# side effect. A FIRST import that happens inside a test whose fixture has
# replaced `_REGISTRY` registers into the temporary dict, which is discarded on
# teardown — and the module is now in `sys.modules`, so it never registers
# again. Every later test in the process then sees a registry missing `tidmad`,
# and the failure surfaces in an unrelated module.
#
# Found exactly that way: C1 imported `tidmad_data_path` inside a test body,
# and `test_step10_p1_c3_transport.py` failed three modules later. Collection
# is the one moment guaranteed to precede every test.
import execute_tools.davis_data_path
import execute_tools.pets_data_path
import execute_tools.task_data_path as tdp
import execute_tools.tidmad_data_path
from execute_tools.task_data_path import (
    TASK_DATA_PATH_ARGV_FLAG,
    TASK_DATA_PATH_IDENTITY_FLAG,
    TaskDataPathIdentityError,
    content_identity,
    register_task_data_path,
    resolve_transported_task_data_path,
    transport_argv,
    verify_transported_identity,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: The ONE resolution authority every child calls (C3's four-row table).
CHILD_RESOLVER = "resolve_child_task_data_path"

CHILDREN = (
    "execute_tools/train_engine_sandbox.py",
    "execute_tools/inference_single.py",
    "execute_tools/denoising_score_single.py",
)


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    monkeypatch.setattr(tdp, "_REGISTRY", {})
    monkeypatch.setattr(tdp, "_CONTENT", {})


def _impl(id_: str = "c2_impl", *, cls_name: str = "Impl", spy: list | None = None):
    def _consume(self, *a, **k):
        if spy is not None:  # pragma: no cover - the assertion is that it is NOT called
            spy.append("consumed")
        return None

    ns = {"task_data_path_id": id_}
    for method in (
        "training_dataset",
        "validation_dataset",
        "write_deliverable",
        "read_evaluation_payload",
    ):
        ns[method] = _consume
    return type(cls_name, (), ns)()


# ======================================================================
# The parent pins
# ======================================================================


class TestTheParentPinsTheIdentity:
    def test_the_transport_carries_the_id_AND_the_identity(self):
        impl = _impl()
        fragment = transport_argv(impl)
        assert fragment[0] == TASK_DATA_PATH_ARGV_FLAG
        assert fragment[1] == "c2_impl"
        assert fragment[2] == TASK_DATA_PATH_IDENTITY_FLAG
        assert fragment[3] == content_identity(impl)

    def test_the_identity_comes_from_the_IMPLEMENTATION_not_a_free_string(self):
        """The same single-authority rule the id already follows: the emitter
        takes the implementation, so the transported identity cannot be
        anything other than the resolved binding's own.

        UPGRADED at F-12bc-7. This used to require `content_identity(impl)`
        literally — a direct file read — and that was precisely the defect:
        the emitter must use the identity CAPTURED at registration, or the pin
        follows the edit it exists to catch. The property being asserted is
        unchanged (the identity is derived from the implementation, not
        supplied); what changed is which derivation is correct.
        """
        fn = next(
            n
            for n in ast.walk(
                ast.parse((REPO_ROOT / "execute_tools" / "task_data_path.py").read_text())
            )
            if isinstance(n, ast.FunctionDef) and n.name == "transport_argv"
        )
        rendered = ast.unparse(fn)
        assert [a.arg for a in fn.args.args] == ["impl"]
        assert "effective_identity(impl)" in rendered
        assert "content_identity(impl)" not in rendered, (
            "the emitter re-reads the plugin file at transport time — F-12bc-7"
        )

    def test_it_is_emitted_only_when_composed(self):
        """The R-11-1 precedent: an un-composed run's argv is unchanged. The
        parent-side emitter is keyed on the BINDING, so no binding means no
        fragment at all — including no identity.
        """
        src = (REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8")
        fn = src[src.index("def _task_data_path_argv") : src.index("def _task_manifest_argv")]
        assert "return transport_argv(bound) if bound is not None else []" in fn


# ======================================================================
# The child verifies — BEFORE consuming
# ======================================================================


class TestTheChildVerifiesBeforeConsuming:
    def test_a_matching_identity_resolves(self):
        impl = _impl()
        register_task_data_path(impl)
        assert resolve_transported_task_data_path("c2_impl", content_identity(impl)) is impl

    def test_a_REGISTRY_HIT_with_divergent_content_is_REFUSED(self):
        """Parent §7's sharp edge. The id resolves perfectly — that is exactly
        the dangerous case, because a registry hit LOOKS like proof.
        """
        register_task_data_path(_impl(cls_name="Registered"))
        pinned = content_identity(_impl(cls_name="WhatTheParentHad"))
        with pytest.raises(TaskDataPathIdentityError) as exc:
            resolve_transported_task_data_path("c2_impl", pinned)
        message = str(exc.value)
        assert "parent pinned:" in message
        assert "child resolved:" in message
        assert "a registry hit" in message.lower()

    def test_the_semantic_is_NEVER_CONSUMED_on_divergence(self):
        """The acceptance criterion, proven with a spy rather than inferred
        from call order. Every one of the four contract methods records if it
        is reached; none may be.
        """
        spy: list[str] = []
        register_task_data_path(_impl(cls_name="Registered", spy=spy))
        pinned = content_identity(_impl(cls_name="Different"))
        with pytest.raises(TaskDataPathIdentityError):
            resolve_transported_task_data_path("c2_impl", pinned)
        assert spy == [], (
            "the implementation was consumed before its identity was verified — "
            "the check has moved after the thing it protects"
        )

    def test_an_absent_identity_is_an_ABSENCE_OF_A_CLAIM(self):
        """A parent that predates this transport pinned nothing. A child must
        not invent a requirement for it — that would make every legacy run
        fail on a check its parent never made.
        """
        impl = _impl()
        register_task_data_path(impl)
        assert resolve_transported_task_data_path("c2_impl", None) is impl
        assert verify_transported_identity(impl, None) is impl

    def test_an_unknown_id_still_fails_at_RESOLUTION_not_identity(self):
        """The two failures stay distinguishable: "I cannot find it" and "I
        found something else" are different problems and read differently.
        """
        from execute_tools.task_data_path import TaskDataPathResolutionError

        with pytest.raises(TaskDataPathResolutionError):
            resolve_transported_task_data_path("c2_absent", "anything")


class TestEveryChildGoesThroughTheCheck:
    @pytest.mark.parametrize("child", CHILDREN)
    def test_the_child_parses_the_identity_flag(self, child):
        src = (REPO_ROOT / child).read_text(encoding="utf-8")
        assert '"--task_data_path_identity"' in src

    @pytest.mark.parametrize("child", CHILDREN)
    def test_the_child_PASSES_it_to_the_resolver(self, child):
        """A flag parsed and then dropped is the transport-drop defect
        OD-S7-1 by another name: the check would silently become a no-op with
        every test still green.

        Named on ``resolve_child_task_data_path`` since C3 moved all three
        children onto the four-row resolver. That flip is why the assertion is
        *"the child passes what it parsed"* rather than *"the child calls this
        function"* — the second phrasing would have to be rewritten every time
        the resolver moves, and would say nothing about whether the value
        survives the move.
        """
        tree = ast.parse((REPO_ROOT / child).read_text(encoding="utf-8"))
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == CHILD_RESOLVER
        ]
        assert calls, f"{child} no longer resolves a transported data path"
        for call in calls:
            rendered = ast.unparse(call)
            assert "task_data_path_identity" in rendered, (
                f"{child} parses the identity but does not pass it — the check "
                f"is a no-op and every test would still pass"
            )

    @pytest.mark.parametrize("child", CHILDREN)
    def test_no_child_bypasses_the_four_row_resolver(self, child):
        """One resolution authority, not two. C3's composing route is the only
        thing that lets an out-of-tree id resolve here, so a child that still
        called the registry-only entry point would work for the built-ins and
        fail for exactly the tasks this PR exists to support.
        """
        tree = ast.parse((REPO_ROOT / child).read_text(encoding="utf-8"))
        direct = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "resolve_transported_task_data_path"
        ]
        assert not direct, (
            f"{child} calls the registry-only resolver directly — an "
            f"out-of-tree implementation would be unresolvable in this child "
            f"while resolving perfectly in the parent that spawned it"
        )

    def test_the_check_lives_in_the_ONE_function_every_child_calls(self):
        """Not duplicated per child. A per-child copy is a per-child chance to
        forget, and the census above could not tell a correct copy from a
        subtly wrong one.

        Both rows of the four-row table are covered: the HIT row delegates to
        ``resolve_transported_task_data_path`` (which verifies), and the
        composing row verifies before returning.
        """
        registry_row = next(
            n
            for n in ast.walk(
                ast.parse((REPO_ROOT / "execute_tools" / "task_data_path.py").read_text())
            )
            if isinstance(n, ast.FunctionDef) and n.name == "resolve_transported_task_data_path"
        )
        assert "verify_transported_identity" in ast.unparse(registry_row)

        composing_row = next(
            n
            for n in ast.walk(
                ast.parse((REPO_ROOT / "workflows" / "task_composition.py").read_text())
            )
            if isinstance(n, ast.FunctionDef) and n.name == CHILD_RESOLVER
        )
        rendered = ast.unparse(composing_row)
        assert "resolve_transported_task_data_path" in rendered, (
            "the HIT row no longer delegates to the registry authority"
        )
        assert "verify_transported_identity" in rendered, (
            "the COMPOSING row returns an implementation without verifying it "
            "against the parent's pin — an id the child composes itself is "
            "exactly as unproven as one it looked up"
        )

    @pytest.mark.parametrize("child", CHILDREN)
    def test_no_child_reimplements_the_verification(self, child):
        src = (REPO_ROOT / child).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
        assert "content_identity(" not in code, (
            f"{child} computes an identity itself — verification has ONE owner"
        )


# ======================================================================
# The three divergence cases — genuinely three, on real files
# ======================================================================

_PLUGIN = textwrap.dedent(
    """
    class {cls}:
        task_data_path_id = "c2_plugin"

        def training_dataset(self, scope, params):
            return {marker!r}

        def validation_dataset(self, scope, params): ...
        def write_deliverable(self, outputs, request): ...
        def read_evaluation_payload(self, request): ...
    """
)


def _load_plugin(path, symbol):
    """Load a plugin through the PRODUCTION loader — not a simulation of it.

    Written first as a hand-rolled ``spec_from_file_location`` and it produced
    a weaker identity than production does: ``content_identity`` reads the
    defining module out of ``sys.modules``, which the real loader populates and
    my imitation did not, so both loads degraded to the qualname-only fallback
    and an edited plugin compared EQUAL. The fallback is correct (a class with
    no readable module has no content to hash); the test was wrong to exercise
    it while claiming to test the production path.
    """
    from workflows.task_composition import _load_symbol

    cls, _ref = _load_symbol({"file": str(path), "symbol": symbol}, str(path.parent), "c2 probe")
    return cls()


class TestTheThreeDivergenceCases:
    """§M / C2 acceptance criterion 1. Three distinct causes, not three names
    for one assertion:

    * the **plugin bytes** changed under an unchanged manifest;
    * the **manifest** changed to name a different symbol in the same file;
    * the **registry** answers with something else entirely (above).

    The first two are proven on real files through a real loader, because the
    thing being claimed is that an EDIT is detected — and an edit is a
    filesystem event, not a Python object.
    """

    def test_edited_plugin_BYTES_diverge(self, tmp_path):
        plugin = tmp_path / "p.py"
        plugin.write_text(_PLUGIN.format(cls="Impl", marker="original"), encoding="utf-8")
        pinned = content_identity(_load_plugin(plugin, "Impl"))

        # the bind-to-spawn window: same path, same symbol, different code
        plugin.write_text(_PLUGIN.format(cls="Impl", marker="EDITED"), encoding="utf-8")
        edited = _load_plugin(plugin, "Impl")

        assert content_identity(edited) != pinned
        with pytest.raises(TaskDataPathIdentityError):
            verify_transported_identity(edited, pinned)

    def test_an_UNEDITED_plugin_does_not(self, tmp_path):
        """The half that makes the test above mean something. Without it, an
        identity that changed on every load would pass the divergence test and
        refuse every legitimate run.
        """
        plugin = tmp_path / "p.py"
        plugin.write_text(_PLUGIN.format(cls="Impl", marker="original"), encoding="utf-8")
        first = _load_plugin(plugin, "Impl")
        second = _load_plugin(plugin, "Impl")
        assert content_identity(second) == content_identity(first)
        assert verify_transported_identity(second, content_identity(first)) is second

    def test_an_edited_MANIFEST_naming_another_symbol_diverges(self, tmp_path):
        """The manifest is data, and data can be edited between the parent
        resolving it and the child reading it. Same file, same bytes, a
        different declared symbol — and a check that hashed only the FILE
        would call these one implementation.
        """
        plugin = tmp_path / "p.py"
        plugin.write_text(
            _PLUGIN.format(cls="Declared", marker="a") + _PLUGIN.format(cls="Other", marker="b"),
            encoding="utf-8",
        )
        pinned = content_identity(_load_plugin(plugin, "Declared"))
        swapped = _load_plugin(plugin, "Other")

        assert content_identity(swapped) != pinned, (
            "two symbols in one file share an identity — the identity is "
            "file-scoped where it must be symbol-scoped"
        )
        with pytest.raises(TaskDataPathIdentityError):
            verify_transported_identity(swapped, pinned)


class TestARegistryHitIsNeverIdentityProof:
    """§M / C2 acceptance criterion 2, as a census.

    Two production paths hand a caller an implementation looked up by NAME.
    Both must compare content before the caller can consume it — and stating
    it as a census rather than two isolated tests is what makes a THIRD such
    path fail here instead of shipping.
    """

    def test_every_name_keyed_lookup_that_yields_a_consumable_impl_compares_content(self):
        sites = {
            (
                REPO_ROOT / "execute_tools" / "task_data_path.py",
                "def resolve_transported_task_data_path",
            ): "verify_transported_identity",
            (
                REPO_ROOT / "workflows" / "task_composition.py",
                "def _compose_task_data_path",
            ): "registered_content_identity",
        }
        for (path, anchor), required in sites.items():
            name = anchor.removeprefix("def ")
            fn = next(
                (
                    n
                    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                    if isinstance(n, ast.FunctionDef) and n.name == name
                ),
                None,
            )
            assert fn is not None, f"{path.name} no longer defines {name}"
            body = ast.unparse(fn)
            assert required in body, (
                f"{path.name}{anchor} resolves by name without comparing content — "
                f"a stale registration would be consumed as though it were the "
                f"implementation the parent pinned"
            )

    def test_the_registry_lookup_itself_is_content_blind_ON_PURPOSE(self):
        """Which is exactly why the verification is a separate step. The
        registry answers "what is registered under this name?" — a correct
        answer to a different question.
        """
        register_task_data_path(_impl(cls_name="Registered"))
        from execute_tools.task_data_path import (
            TaskBindingContext,
            resolve_task_data_path,
        )

        assert resolve_task_data_path(TaskBindingContext(task_data_path_id="c2_impl")) is not None


class TestTheUnComposedChildIsUnaffected:
    """§M / C2 acceptance criterion 3. R-11-1's standing rule: a run that
    declares no composition emits no composition argv — the identity included.
    """

    def test_neither_flag_appears_in_an_un_composed_child_argv(self, tmp_path):
        from core.sandbox_executor import TidmadSandbox
        from tests.unit.workflows.test_step10_p1_c0_census import (
            capture_uncomposed_child_argv,
        )

        sandbox = TidmadSandbox(run_name="c2run", workspace=str(tmp_path), progress_bar=False)
        for phase, cmd in capture_uncomposed_child_argv(sandbox, tmp_path).items():
            assert TASK_DATA_PATH_ARGV_FLAG not in cmd, f"{phase}: {cmd}"
            assert TASK_DATA_PATH_IDENTITY_FLAG not in cmd, (
                f"the un-composed {phase} child gained an identity flag — the "
                f"legacy argv is no longer byte-identical: {cmd}"
            )


# ======================================================================
# What identity is, and is not
# ======================================================================


class TestTheIdentityIsPerFamilyNotTheFingerprint:
    def test_it_does_not_mention_the_composition_fingerprint(self):
        """D-BC-5. The fingerprint has its own owner (the run-invariants lock)
        and answers a different question; using it here would refuse for
        changes the child never consumes and could not say which.
        """
        src = (REPO_ROOT / "execute_tools" / "task_data_path.py").read_text(encoding="utf-8")
        fn = src[
            src.index("def verify_transported_identity") : src.index(
                "def resolve_transported_task_data_path"
            )
        ]
        for word in ("fingerprint", "semantic_fingerprint", "manifest"):
            assert word not in fn

    def test_the_refusal_names_the_FAMILY_that_diverged(self):
        """The diagnostic value the fingerprint could not give: which thing
        moved, so an operator knows what to look at.
        """
        register_task_data_path(_impl(cls_name="Registered"))
        with pytest.raises(TaskDataPathIdentityError) as exc:
            resolve_transported_task_data_path("c2_impl", content_identity(_impl(cls_name="Other")))
        assert "c2_impl" in str(exc.value)

    def test_re_reading_the_manifest_is_not_the_mechanism(self):
        """Explicitly excluded by the frozen design, and rightly: re-reading
        proves the manifest is readable, not that the code about to execute is
        the code the parent resolved.
        """
        src = (REPO_ROOT / "execute_tools" / "task_data_path.py").read_text(encoding="utf-8")
        fn = src[
            src.index("def verify_transported_identity") : src.index(
                "def resolve_transported_task_data_path"
            )
        ]
        for reading in ("open(", "read_text", "json.load", "yaml"):
            assert reading not in fn


# ======================================================================
# F-12bc-7 — the pin must not be a re-read
# ======================================================================


class TestThePinIsCapturedNotReRead:
    """Found by `G-12bc-C`, which FAILED on its first launch.

    `content_identity` hashes the defining module's SOURCE FILE, so it
    re-reads the disk on every call. C2 used it directly in `transport_argv`,
    which meant the "parent-pinned identity" was re-derived at SPAWN time from
    whatever was on disk then::

        parent registers   -> captured   cb1a75b3…   (a real pin)
        plugin edited      ->
        parent spawns      -> transported 469101f4…  (a re-read — it FOLLOWS
        child composes     -> computed    469101f4…   the edit, and matches)

    The comparison passed and the child ran the tampered plugin. The window C2
    exists to close was wide open, and every C2 unit test was green.

    **Why they were green** is the transferable part. Each of them computed
    `pinned = content_identity(...)` and held the resulting STRING across the
    edit — so the test pinned a value while production pinned a *function
    call*. A test that captures what production recomputes cannot see a
    recomputation defect, no matter how adversarial the scenario around it is.
    These assert through the production emitter instead.
    """

    def test_the_transported_identity_does_not_follow_an_edit(self, tmp_path):
        fixture = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task"
        import shutil

        from workflows.task_composition import compose_run_task_bindings

        root = tmp_path / "ft"
        shutil.copytree(fixture, root)
        composition = compose_run_task_bindings(str(root / "composition.yaml"))
        impl = composition.task_data_path
        before = transport_argv(impl)[3]

        plugin = root / "plugins" / "spectro_data_path.py"
        plugin.write_text(
            plugin.read_text(encoding="utf-8") + "\n# EDITED AFTER THE PARENT PINNED\n",
            encoding="utf-8",
        )

        assert transport_argv(impl)[3] == before, (
            "the transported identity changed when the plugin FILE changed — "
            "it is a re-read, not a pin, so it follows the very edit it exists "
            "to catch (F-12bc-7)"
        )

    def test_the_pin_is_the_value_captured_at_registration(self):
        from execute_tools.task_data_path import (
            effective_identity,
            registered_content_identity,
        )

        impl = _impl()
        register_task_data_path(impl)
        assert effective_identity(impl) == registered_content_identity("c2_impl")

    def test_an_unregistered_implementation_still_gets_an_identity(self):
        """The fallback, and why it is not a hole: nothing captured an
        identity for an implementation nobody registered, and there is no
        on-disk edit to miss for one that was constructed in memory. Every
        production route registers.
        """
        from execute_tools.task_data_path import effective_identity

        impl = _impl()
        assert effective_identity(impl) == content_identity(impl)

    def test_verification_also_compares_the_CAPTURED_identity(self):
        """Same reason, child side: the check must describe the code that is
        LOADED here, not the bytes the plugin file happens to hold now.
        """
        fn = next(
            n
            for n in ast.walk(
                ast.parse((REPO_ROOT / "execute_tools" / "task_data_path.py").read_text())
            )
            if isinstance(n, ast.FunctionDef) and n.name == "verify_transported_identity"
        )
        rendered = ast.unparse(fn)
        assert "effective_identity(impl)" in rendered
        assert "content_identity(impl)" not in rendered
