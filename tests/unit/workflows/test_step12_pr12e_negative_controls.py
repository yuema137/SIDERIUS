"""Step 12 / PR-12e — the executed negative-control matrix, N1..N9 and N11.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12e_out_of_tree_graduation.md`` §J (the matrix), §C.2 (two facts not to
re-derive), §H (validation economy).

------------------------------------------------------------------------
WHAT A NEGATIVE CONTROL IS FOR HERE
------------------------------------------------------------------------

The positive claim — *a fourth task, living outside the repository, runs* —
is worth very little on its own. A framework that silently substituted
TIDMAD's data path, TIDMAD's metric and TIDMAD's deliverable naming would
also produce a green run. What separates "the package executed" from "the
package was quietly ignored" is a set of controls that BREAK the package in
one specific way each, and require the framework to refuse **by name**.

``N10`` is workstream C's (the restore family) and is deliberately absent.

------------------------------------------------------------------------
COST — §14a.4, and why none of these spawns a training chain
------------------------------------------------------------------------

    *"Executed against the real package" is a statement about the ARTIFACT
    under test, not a licence to re-burn the full workflow per control.*

Each row is discharged by a deterministic in-process proof, and the rows
whose failure class only exists ACROSS A PROCESS BOUNDARY additionally get a
**cheap C-class subprocess witness** — a fresh interpreter that calls the
same production authority a real child calls
(``resolve_child_task_data_path``), with no training, no inference, no GPU
and no launcher. Every refusal these controls test happens strictly BEFORE
any child would be spawned, which is why no control needs a chain to observe
it.

------------------------------------------------------------------------
THE VEHICLE, AND WHY ONE BODY SERVES BOTH PHASES
------------------------------------------------------------------------

The out-of-tree package is workstream A's deliverable and binds at the
integration checkpoint through ``SIDERIUS_12E_PACKAGE_ROOT``. Until then the
same test bodies run against the in-repo composition fixture
(``tests/fixtures/step10_p1/fourth_task``), which is a *mechanism* vehicle —
it composes through the identical production authorities. When the variable
is set, :func:`materialize_vehicle` copies the REAL package instead and every
control below re-runs against it **with no code change**, which is what §J
means by "executed against the real package".

``TestTheControlsRanAgainstTheRealPackage`` is the integration-evidence row:
it SKIPS while unbound and asserts the real artifact was used once it is, so
a Gate cannot report this matrix as discharged while it only ever saw the
fixture.

------------------------------------------------------------------------
TWO FACTS THESE CONTROLS DO NOT RE-DERIVE (§C.2, from 12d §P)
------------------------------------------------------------------------

1. **Identity pinning covers the ``task_data_path`` family ONLY.** The metric
   and deliverable-naming families are re-composed child-side with no parent
   pin — deliberate, pinned by ``test_step12_pr12bc_c2_identity.py:477``.
   N2 and N8 therefore target ``task_data_path``; asserting a pin on the two
   families that deliberately lack one would fail for the wrong reason and
   read as a defect in this PR.
2. **``run_registration_scope`` has zero production callers.** CASE A's
   production protection is the two-phase content-equality rule, because
   production runs one process per iteration. N4 exercises that rule and
   makes no claim about an in-process overlay.

And the F-12bc-7 lesson, which shapes N2 and N8 specifically: **the
transported identity is the value CAPTURED at registration, never a fresh
read of the plugin file.** A control that captured the digest as a string and
compared it across the edit would certify nothing — so every identity
assertion below goes through the production emitter
(``transport_argv`` / ``resolve_child_task_data_path``) rather than through a
value this module computed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

import execute_tools.task_data_path as tdp
from execute_tools.task_data_path import (
    TASK_DATA_PATH_IDENTITY_FLAG,
    TaskBindingContext,
    TaskDataPathIdentityError,
    TaskDataPathRegistrationError,
    TaskDataPathResolutionError,
    resolve_task_data_path,
    transport_argv,
)
from tests.unit.guardrails.test_step12_pr12e_census import (
    PACKAGE_ROOT_ENV,
    package_root_from_env,
)
from workflows.task_composition import (
    TaskCompositionError,
    compose_run_task_bindings,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The in-repo mechanism vehicle. NOT the graduation vehicle — parent §16 is
#: explicit that `spectro_segmentation_v0` is a composition fixture whose name
#: is already burned into the census, so reusing it as the FOURTH TASK would
#: make the zero-core-edit census vacuous. Reusing it as a mechanism vehicle
#: for refusal behaviour is a different thing, and it is why these controls
#: are green before workstream A lands anything.
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task"

#: The modules whose import registers a shipped implementation — the
#: built-ins' bootstrap, which Step 08b's sentence distinguishes from the
#: extension path.
_BUILTIN_MODULES = frozenset({"execute_tools.tidmad_data_path"})

# Only the bounded uncomposed compatibility implementation is framework
# bootstrap state now. Real task packages compose through their manifests.
tdp.bootstrap_legacy_tidmad_data_path()


def _builtin_ids() -> tuple[str, ...]:
    """The ids the three shipped modules registered — DERIVED, never listed.

    A literal list here would be the F-12bc-6 shape: the first draft of this
    module guessed ``("tidmad", "pets", "davis")`` and two of the three were
    wrong (they are ``oxford_iiit_pet`` and ``davis_future_prediction``), so
    N6's collision fixture registered a FRESH id instead of colliding — and
    the control would have reported "no refusal" for a case it never set up.
    Reading the registry keeps this correct through any future rename.
    """
    return tuple(
        sorted(
            impl_id
            for impl_id, impl in tdp._REGISTRY.items()
            if type(impl).__module__ in _BUILTIN_MODULES
        )
    )


#: Snapshotted at COLLECTION, after the three bootstrap imports above and
#: before any fixture has replaced the registry.
_BUILTIN_IDS = _builtin_ids()


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    """A registry holding exactly the built-ins.

    Not a blanked one: N6 needs ``tidmad`` present to collide with, and
    blanking would make the collision unreachable while the test still passed
    for a different reason. Not the live one either: another module composing
    the fixture leaks its id, and a leaked registration turns N2's setup into
    N4's failure.
    """
    assert _BUILTIN_IDS, (
        "no shipped implementation is registered — the built-ins' bootstrap "
        "did not run, so N6 would have nothing to collide with and would pass "
        "for the wrong reason (F-12bc-8: a module imported under a blanked "
        "registry never registers again)"
    )
    monkeypatch.setattr(
        tdp, "_REGISTRY", {k: v for k, v in tdp._REGISTRY.items() if k in _BUILTIN_IDS}
    )
    monkeypatch.setattr(
        tdp, "_CONTENT", {k: v for k, v in tdp._CONTENT.items() if k in _BUILTIN_IDS}
    )


# ======================================================================
# The vehicle
# ======================================================================


@dataclass(frozen=True, slots=True)
class Vehicle:
    """A writable copy of the task package under test."""

    root: Path
    manifest: Path
    task_id: str
    plugin: Path
    is_real: bool


def materialize_vehicle(tmp_path: Path, name: str = "pkg") -> Vehicle:
    """Copy the package under test into ``tmp_path`` so a control can break it.

    Never mutates the source: a control that edited the real package would
    corrupt workstream A's artifact and, worse, would leave the next control
    running against a package the previous one broke.
    """
    source = package_root_from_env() or FIXTURE_ROOT
    is_real = package_root_from_env() is not None
    root = tmp_path / name
    shutil.copytree(source, root)
    manifest = root / "composition.yaml"
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    section = raw["task_data_path"]
    plugin_ref = section.get("file")
    if plugin_ref is None:
        pytest.skip(
            "the package declares its data path as an importable `module:` "
            "rather than an out-of-tree `file:`. The identity controls (N2, "
            "N3, N8) are about a plugin FILE's content, and there is none — "
            "named rather than silently passing."
        )
    return Vehicle(
        root=root,
        manifest=manifest,
        task_id=section["id"],
        plugin=root / plugin_ref,
        is_real=is_real,
    )


def _rewrite_manifest(vehicle: Vehicle, mutate) -> None:
    raw = yaml.safe_load(vehicle.manifest.read_text(encoding="utf-8"))
    mutate(raw)
    vehicle.manifest.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


# ======================================================================
# The cheap C-class subprocess witness
# ======================================================================
#
# A fresh interpreter calling the SAME child-side authority every real child
# calls. No launcher, no training script, no GPU — `tests/unit/conftest.py`'s
# heavy-subprocess guard is satisfied by construction because none of the
# forbidden script names appears in the argv.

_COMPOSE_WITNESS = """
import json, sys
from workflows.task_composition import compose_run_task_bindings
try:
    composition = compose_run_task_bindings(sys.argv[1])
except BaseException as exc:
    print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
    raise SystemExit(3)
print(json.dumps({"ok": True, "task_data_path_id": composition.task_data_path_id}))
"""

_CHILD_WITNESS = """
import json, os, sys
from workflows.task_composition import resolve_child_task_data_path
manifest, task_id, identity = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    impl = resolve_child_task_data_path(
        task_id,
        identity=None if identity == "-" else identity,
        manifest_path=manifest,
    )
except BaseException as exc:
    print(json.dumps({"error": type(exc).__name__, "message": str(exc), "pid": os.getpid()}))
    raise SystemExit(3)
print(json.dumps({"ok": True, "resolved": impl.task_data_path_id, "pid": os.getpid()}))
"""

_PARENT_PIN_WITNESS = """
import json, os, sys
from workflows.task_composition import compose_run_task_bindings
from execute_tools.task_data_path import transport_argv
composition = compose_run_task_bindings(sys.argv[1])
argv = transport_argv(composition.task_data_path)
print(json.dumps({"argv": argv, "pid": os.getpid()}))
"""


@dataclass(frozen=True, slots=True)
class WitnessResult:
    returncode: int
    payload: dict
    stderr: str


def run_witness(code: str, *args: str) -> WitnessResult:
    """Run one cheap witness process and parse its single JSON line."""
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    line = next((ln for ln in reversed(completed.stdout.splitlines()) if ln.startswith("{")), "")
    payload = json.loads(line) if line else {}
    return WitnessResult(completed.returncode, payload, completed.stderr)


# ======================================================================
# N1 — package removed
# ======================================================================


class TestN1PackageRemoved:
    """§J N1 · failure class: the composition cannot resolve a declared family.
    Earliest expected refusal: the composition root, BEFORE any spawn.

    This is also §I.4, the census's own negative control: *with the package
    path removed, the same command must fail closed with the composition's
    named error.* Without it, a census could pass on a run that never actually
    depended on the external package — which is the difference between "the
    framework needed no edit" and "the framework never used the package".

    **How these fail when the behaviour breaks**: make any composition branch
    fall back to a legacy default and the refusal disappears; the assertions
    are on the REFUSAL, so a silent success is the failure.
    """

    def test_a_removed_manifest_refuses_by_name(self, tmp_path):
        vehicle = materialize_vehicle(tmp_path)
        vehicle.manifest.unlink()
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        message = str(exc.value)
        assert "not found" in message
        assert str(vehicle.manifest) in message
        assert "legacy defaults" in message, (
            "the refusal must say WHY it fails closed — an operator who reads "
            "'not found' alone will assume a default was used"
        )

    def test_a_removed_plugin_file_refuses_naming_the_file(self, tmp_path):
        """The sharper half: the manifest is intact, so a framework that
        resolved families by convention rather than by declaration would
        happily proceed."""
        vehicle = materialize_vehicle(tmp_path)
        vehicle.plugin.unlink()
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        message = str(exc.value)
        assert "task_data_path" in message
        assert "does not exist" in message
        assert "not a scan candidate" in message

    def test_the_refusal_precedes_ANY_subprocess(self, tmp_path, monkeypatch):
        """'Before any spawn' asserted rather than assumed.

        A bare ``spawned == []`` would pass for two very different reasons —
        composition really spawned nothing, or the sentinel was never
        installed. So the sentinel is ARMED at the end: the same patched
        ``subprocess.run`` must raise when this test calls it. Without that
        line the assertion proves nothing about a future pre-flight child.
        """
        spawned: list[object] = []

        def _refuse(*args, **kwargs):
            spawned.append(args)
            raise AssertionError("composition spawned a process before refusing")

        monkeypatch.setattr(subprocess, "Popen", _refuse)
        monkeypatch.setattr(subprocess, "run", _refuse)

        vehicle = materialize_vehicle(tmp_path)
        vehicle.plugin.unlink()
        with pytest.raises(TaskCompositionError):
            compose_run_task_bindings(str(vehicle.manifest))
        assert spawned == []

        with pytest.raises(AssertionError, match="spawned a process"):
            subprocess.run(["true"])  # the sentinel is live

    def test_the_cheap_subprocess_witness_exits_non_zero(self, tmp_path):
        """§J's required evidence: *the composition's named error; run exits
        non-zero.* An in-process ``pytest.raises`` cannot show the exit code,
        and an exit code is what an operator's shell sees."""
        vehicle = materialize_vehicle(tmp_path)
        vehicle.plugin.unlink()
        result = run_witness(_COMPOSE_WITNESS, str(vehicle.manifest))
        assert result.returncode == 3, result.stderr
        assert result.payload["error"] == TaskCompositionError.__name__
        assert "does not exist" in result.payload["message"]

    def test_the_INTACT_package_composes_in_the_same_witness(self, tmp_path):
        """The half that makes N1 mean something. Without it, a witness that
        exited non-zero for ANY input would look identical to one that
        detected the removal."""
        vehicle = materialize_vehicle(tmp_path)
        result = run_witness(_COMPOSE_WITNESS, str(vehicle.manifest))
        assert result.returncode == 0, result.stderr
        assert result.payload["task_data_path_id"] == vehicle.task_id


# ======================================================================
# N2 — plugin edited after the identity pin
# ======================================================================


class TestN2PluginEditedAfterTheIdentityPin:
    """§J N2 · failure class: content identity divergence.
    Earliest expected refusal: child-side identity verification, BEFORE
    consumption. Evidence: a ``TaskDataPathIdentityError``-class refusal
    naming BOTH identities.

    **Why the witness must cross a process boundary.** In the parent, the
    registry holds the identity CAPTURED at registration, so an edit to the
    plugin file changes nothing the parent reports — that is F-12bc-7 working
    correctly, and 12bc's C2 suite already pins it. The divergence only
    becomes observable when a SECOND process loads the edited file and
    captures a different identity. A same-process control here would assert
    the opposite of the defect it exists to catch.
    """

    def test_the_parent_pin_does_not_follow_the_edit(self, tmp_path):
        """F-12bc-7, asserted through the production emitter rather than
        through a string this test captured. A test that held the digest as a
        value across the edit would pass even if ``transport_argv`` re-read the
        file — which is exactly how every C2 unit test was green while the
        window was wide open."""
        vehicle = materialize_vehicle(tmp_path)
        composition = compose_run_task_bindings(str(vehicle.manifest))
        pinned = transport_argv(composition.task_data_path)[3]
        vehicle.plugin.write_text(
            vehicle.plugin.read_text(encoding="utf-8") + "\n# EDITED AFTER THE PIN\n",
            encoding="utf-8",
        )
        assert transport_argv(composition.task_data_path)[3] == pinned

    def test_the_child_REFUSES_the_edited_plugin_naming_both_identities(self, tmp_path):
        vehicle = materialize_vehicle(tmp_path)
        parent = run_witness(_PARENT_PIN_WITNESS, str(vehicle.manifest))
        assert parent.returncode == 0, parent.stderr
        pinned = parent.payload["argv"][3]

        vehicle.plugin.write_text(
            vehicle.plugin.read_text(encoding="utf-8") + "\n# EDITED AFTER THE PIN\n",
            encoding="utf-8",
        )
        child = run_witness(_CHILD_WITNESS, str(vehicle.manifest), vehicle.task_id, pinned)

        assert child.returncode == 3, child.stderr
        assert child.payload["error"] == TaskDataPathIdentityError.__name__
        message = child.payload["message"]
        assert "parent pinned" in message and "child resolved" in message
        assert pinned in message, "the refusal does not name the PARENT's identity"
        assert message.count("@") >= 2, (
            "the refusal names fewer than two content identities — an operator "
            "cannot see which side moved"
        )
        assert child.payload["pid"] != parent.payload["pid"]

    def test_an_UNEDITED_plugin_is_accepted_by_the_same_child(self, tmp_path):
        """The other half. A child that refused everything would pass the row
        above and break every legitimate run."""
        vehicle = materialize_vehicle(tmp_path)
        parent = run_witness(_PARENT_PIN_WITNESS, str(vehicle.manifest))
        pinned = parent.payload["argv"][3]
        child = run_witness(_CHILD_WITNESS, str(vehicle.manifest), vehicle.task_id, pinned)
        assert child.returncode == 0, child.stderr
        assert child.payload["resolved"] == vehicle.task_id

    def test_the_refusal_happens_BEFORE_the_implementation_is_consumed(self, tmp_path):
        """'Before consumption' is the load-bearing word in §J's refusal
        point. The fixture's four protocol methods all raise
        ``NotImplementedError``; the child reports an identity error, so the
        refusal is reached without any method having run."""
        vehicle = materialize_vehicle(tmp_path)
        parent = run_witness(_PARENT_PIN_WITNESS, str(vehicle.manifest))
        vehicle.plugin.write_text(
            vehicle.plugin.read_text(encoding="utf-8") + "\n# EDITED\n", encoding="utf-8"
        )
        child = run_witness(
            _CHILD_WITNESS, str(vehicle.manifest), vehicle.task_id, parent.payload["argv"][3]
        )
        assert child.payload["error"] == TaskDataPathIdentityError.__name__
        assert "NotImplementedError" not in child.payload["message"]


# ======================================================================
# N3 — package relocated, content unchanged
# ======================================================================


class TestN3PackageRelocatedContentUnchanged:
    """§J N3 · failure class: a FALSE-POSITIVE identity refusal.
    Expected behaviour: it must **NOT** refuse.

    The only row in the matrix whose pass condition is a success, and the one
    that stops N2 from being satisfied by a check that refuses everything.
    Two checkouts of the same task package are the same scientific run, which
    is why ``content_identity`` excludes host paths.

    **How it fails when the behaviour breaks**: make the identity include the
    absolute path and both rows below go red — the in-process one on the
    equality, the subprocess one on an unexpected refusal.
    """

    def test_relocation_leaves_the_identity_equal(self, tmp_path):
        first = materialize_vehicle(tmp_path, "at_path_a")
        composed_a = compose_run_task_bindings(str(first.manifest))
        identity_a = transport_argv(composed_a.task_data_path)[3]

        second = materialize_vehicle(tmp_path, "at_path_b")
        assert second.root != first.root
        composed_b = compose_run_task_bindings(str(second.manifest))
        identity_b = transport_argv(composed_b.task_data_path)[3]

        assert identity_b == identity_a, (
            "the same package at two paths produced two identities — a "
            "relocation would fail a resume for a reason with no scientific "
            "content"
        )

    def test_a_child_at_a_NEW_path_accepts_the_pin_from_the_old_one(self, tmp_path):
        """The cross-process half, which is where relocation actually bites:
        the parent resolved the package where the operator launched it, the
        child resolves it wherever its own argv points."""
        first = materialize_vehicle(tmp_path, "parent_side")
        parent = run_witness(_PARENT_PIN_WITNESS, str(first.manifest))
        assert parent.returncode == 0, parent.stderr

        second = materialize_vehicle(tmp_path, "child_side")
        child = run_witness(
            _CHILD_WITNESS, str(second.manifest), second.task_id, parent.payload["argv"][3]
        )
        assert child.returncode == 0, (
            f"a relocated but byte-identical package was REFUSED: {child.payload}\n{child.stderr}"
        )
        assert child.payload["resolved"] == second.task_id

    def test_relocation_does_not_move_the_composition_fingerprint(self, tmp_path):
        """The same property one authority over. A fingerprint that moved on
        relocation would fail the resume even though identity verification
        passed — Q-P1-2's exclusion rule, restated as a control."""
        first = materialize_vehicle(tmp_path, "fp_a")
        second = materialize_vehicle(tmp_path, "fp_b")
        a = compose_run_task_bindings(str(first.manifest))
        b = compose_run_task_bindings(str(second.manifest))
        assert a.semantic_fingerprint == b.semantic_fingerprint


# ======================================================================
# N4 — content mismatch under the same id
# ======================================================================


class TestN4ContentMismatchUnderOneId:
    """§J N4 · failure class: two implementations claiming one id.
    Earliest expected refusal: registration, by the two-phase rule.

    §C.2's second fact applies: this is the ONLY thing protecting CASE A in
    production, because ``run_registration_scope`` has zero production callers
    and production runs one process per iteration. So the two-phase rule is
    load-bearing, not a convenience.
    """

    def test_same_id_DIFFERENT_content_is_refused_naming_both(self, tmp_path):
        vehicle = materialize_vehicle(tmp_path, "first")
        compose_run_task_bindings(str(vehicle.manifest))

        rival = materialize_vehicle(tmp_path, "rival")
        rival.plugin.write_text(
            rival.plugin.read_text(encoding="utf-8") + "\n# A DIFFERENT IMPLEMENTATION\n",
            encoding="utf-8",
        )
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(rival.manifest))
        message = str(exc.value)
        assert vehicle.task_id in message
        named = set(re.findall(r"[\w.]+@[0-9a-f]{64}", message))
        assert len(named) == 2, (
            f"the refusal must name BOTH contents; it named {sorted(named)}. "
            f"'already registered' alone sends an operator looking for a "
            f"duplicate NAME, when what happened is an EDIT."
        )

    def test_the_refusal_does_not_depend_on_WHERE_the_package_registers(self, tmp_path):
        """The defect only this test catches: a control coupled to the
        package's own authoring style.

        SIDERIUS refuses a same-id/different-content collision at two
        different places, and which one fires is a property of the PACKAGE,
        not of the framework:

        * a plugin that registers at MODULE SCOPE raises inside
          ``_load_symbol``'s import, and the message is the registry's
          (``registered:`` / ``offered:``);
        * a plugin that only defines its class is registered by
          ``_compose_task_data_path``, whose own pre-check speaks
          ``registered:`` / ``loaded:``.

        The first draft asserted one vocabulary and went red the moment
        workstream A gave the real plugin a module-level registration —
        a control failing for the artifact's authoring choice, not for a
        framework defect. So the assertion above counts IDENTITIES, and this
        row states the invariant that makes that legitimate: whichever path
        fires, it is a ``TaskCompositionError`` naming two distinct
        contents.
        """
        vehicle = materialize_vehicle(tmp_path, "base")
        compose_run_task_bindings(str(vehicle.manifest))
        rival = materialize_vehicle(tmp_path, "other")
        rival.plugin.write_text(
            rival.plugin.read_text(encoding="utf-8") + "\n# EDITED\n", encoding="utf-8"
        )
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(rival.manifest))
        message = str(exc.value)
        vocabularies = [
            "registered:" in message and "offered:" in message,
            "registered:" in message and "loaded:" in message,
        ]
        assert any(vocabularies), (
            f"the refusal names neither of the two known content-pair vocabularies: {message}"
        )

    def test_same_id_SAME_content_is_IDEMPOTENT(self, tmp_path):
        """The frozen §8 two-phase rule's other row, and the reason the row
        above is not simply 'duplicate ids are refused'. Before 12bc C1 this
        case ALSO refused, so a module re-executed by a plugin-isolation
        fixture was punished for doing exactly what it did the first time."""
        first = materialize_vehicle(tmp_path, "one")
        second = materialize_vehicle(tmp_path, "two")
        a = compose_run_task_bindings(str(first.manifest))
        b = compose_run_task_bindings(str(second.manifest))
        assert a.task_data_path_id == b.task_data_path_id == first.task_id

    def test_the_registry_entry_point_raises_the_REGISTRATION_error(self, tmp_path):
        """The type §J names, at the authority that owns ids.

        Worth stating precisely, because the two entry points differ: through
        ``compose_run_task_bindings`` the refusal is a ``TaskCompositionError``
        carrying the same two contents (the composition detects the divergence
        in its own pre-check, before ``register_task_data_path`` is reached),
        while through the registry it is a ``TaskDataPathRegistrationError``.
        Both name both contents; a control that asserted only the second type
        would report a failure at the composition boundary that is not one.
        """
        vehicle = materialize_vehicle(tmp_path)
        composition = compose_run_task_bindings(str(vehicle.manifest))
        impostor = type(
            "Impostor",
            (),
            {
                "task_data_path_id": composition.task_data_path_id,
                "training_dataset": lambda self, *a, **k: None,
                "validation_dataset": lambda self, *a, **k: None,
                "write_deliverable": lambda self, *a, **k: None,
                "read_evaluation_payload": lambda self, *a, **k: None,
            },
        )()
        with pytest.raises(TaskDataPathRegistrationError) as exc:
            tdp.register_task_data_path(impostor)
        message = str(exc.value)
        assert "registered:" in message and "offered:" in message


# ======================================================================
# N5 — missing required declaration
# ======================================================================


class TestN5MissingRequiredDeclaration:
    """§J N5 · failure class: an incomplete package.
    Required evidence: the error names the **FAMILY**, not a generic parse
    failure.

    The distinction is the whole row. "Invalid YAML at line 14" sends an
    operator to a text editor; "missing required section ``metric``" sends
    them to the family that is actually absent — and, crucially, proves the
    framework noticed the family was missing rather than resolving its legacy
    default.
    """

    @pytest.mark.parametrize(
        "family", ["task_data_path", "dataset_profile", "metric", "task_health", "task_config"]
    )
    def test_a_missing_section_is_refused_BY_FAMILY(self, family, tmp_path):
        vehicle = materialize_vehicle(tmp_path)
        _rewrite_manifest(vehicle, lambda raw: raw.pop(family, None))
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        message = str(exc.value)
        assert family in message, f"the refusal does not name {family!r}: {message}"
        assert "missing required section" in message
        assert "silently resolve the framework's legacy compatibility default" in message

    def test_a_missing_declaration_FILE_is_refused_by_family(self, tmp_path):
        """One level down: the section is declared and the file it names is
        gone. A framework that treated an unreadable declaration as 'not
        declared' would land in the legacy default."""
        vehicle = materialize_vehicle(tmp_path)
        raw = yaml.safe_load(vehicle.manifest.read_text(encoding="utf-8"))
        declaration = vehicle.root / raw["metric"]["declaration"]
        declaration.unlink()
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        assert "metric declaration" in str(exc.value)
        assert "not found" in str(exc.value)

    def test_a_MISSPELLED_section_is_refused_rather_than_ignored(self, tmp_path):
        """The failure mode a composition exists to prevent: a misspelled
        section silently dropped, leaving its family resolving TIDMAD's
        default. This is N9's shape reached through a typo instead of code."""
        vehicle = materialize_vehicle(tmp_path)

        def _misspell(raw):
            raw["metrics"] = raw.pop("metric")

        _rewrite_manifest(vehicle, _misspell)
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        message = str(exc.value)
        assert "unknown key" in message and "metrics" in message
        assert "refused rather than ignored" in message


# ======================================================================
# N6 — task-id collision with a built-in
# ======================================================================


class TestN6TaskIdCollisionWithABuiltIn:
    """§J N6 · failure class: the id namespace.
    Required evidence: a named refusal, **never silent replacement**.

    The second clause is the one worth executing. A framework that let an
    external package take ``tidmad``'s id would not fail — it would run
    TIDMAD's chain against somebody else's code, and every record would still
    say ``tidmad``.
    """

    def _collide(self, tmp_path: Path, builtin_id: str) -> Vehicle:
        vehicle = materialize_vehicle(tmp_path)
        original = vehicle.plugin.read_text(encoding="utf-8")
        # Only the QUOTED id, in either style: the package names its task in
        # docstrings and error messages too, and rewriting those would change
        # prose rather than the declaration.
        rewritten = original.replace(f'"{vehicle.task_id}"', f'"{builtin_id}"').replace(
            f"'{vehicle.task_id}'", f"'{builtin_id}'"
        )
        assert rewritten != original, (
            f"N6 could not make the plugin CLAIM {builtin_id!r}: no quoted "
            f"{vehicle.task_id!r} literal in {vehicle.plugin.name}. The control "
            f"FAILS rather than skipping — a collision control that silently "
            f"set nothing up reports 'no refusal needed' for a case it never "
            f"created, and §J requires N6 executed."
        )
        vehicle.plugin.write_text(rewritten, encoding="utf-8")
        _rewrite_manifest(vehicle, lambda raw: raw["task_data_path"].update(id=builtin_id))
        return vehicle

    @pytest.mark.parametrize("builtin_id", _BUILTIN_IDS)
    def test_claiming_a_built_in_id_is_refused_by_name(self, builtin_id, tmp_path):
        vehicle = self._collide(tmp_path, builtin_id)
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        assert builtin_id in str(exc.value)

    @pytest.mark.parametrize("builtin_id", _BUILTIN_IDS)
    def test_the_built_in_is_NOT_replaced_by_the_collision(self, builtin_id, tmp_path):
        """The 'never silent replacement' half, asserted at the registry after
        the refusal: the built-in still resolves to the built-in.

        The expected module is READ from the registry before the collision,
        not written down — the id -> module pairing is exactly the kind of
        fact that goes stale (this module's first draft got two of three ids
        wrong)."""
        before = resolve_task_data_path(TaskBindingContext(task_data_path_id=builtin_id))
        origin = type(before).__module__
        assert origin in _BUILTIN_MODULES

        vehicle = self._collide(tmp_path, builtin_id)
        with pytest.raises(TaskCompositionError):
            compose_run_task_bindings(str(vehicle.manifest))

        after = resolve_task_data_path(TaskBindingContext(task_data_path_id=builtin_id))
        assert after is before
        assert type(after).__module__ == origin


# ======================================================================
# N7 — invalid task-owned config (12d seam A)
# ======================================================================


class TestN7InvalidTaskOwnedConfig:
    """§J N7 · failure class: a malformed ``config:`` mapping.
    Required evidence: a named refusal; **never silently ignored**.

    Seam A's rule is that the composition authority checks the SHAPE and never
    a field name — the task's constructor owns the keys. So every refusal here
    must be about shape or about the implementation's own acceptance, and none
    of them may name a task-specific key.
    """

    def _with_config(self, tmp_path: Path, config) -> Vehicle:
        vehicle = materialize_vehicle(tmp_path)
        _rewrite_manifest(vehicle, lambda raw: raw["task_data_path"].update(config=config))
        return vehicle

    def test_a_non_mapping_config_is_refused(self, tmp_path):
        vehicle = self._with_config(tmp_path, [1, 2])
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        assert "task_data_path.config must be a mapping" in str(exc.value)

    def test_a_ref_envelope_with_a_sibling_key_is_refused(self, tmp_path):
        """The misspelling that would otherwise be passed through as an opaque
        mapping and reach the constructor as a dict where a path was meant."""
        vehicle = self._with_config(tmp_path, {"data": {"ref": "data/x.csv", "reff": "y"}})
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        assert "ref envelope carries exactly one key" in str(exc.value)

    def test_an_empty_ref_is_refused(self, tmp_path):
        vehicle = self._with_config(tmp_path, {"data": {"ref": ""}})
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        assert "must be a non-empty string path" in str(exc.value)

    def test_a_key_the_implementation_does_not_accept_is_refused_by_name(self, tmp_path):
        """The refusal that proves the config REACHED the constructor. A
        composition that dropped the mapping would compose successfully — the
        'silently ignored' outcome §J forbids."""
        vehicle = self._with_config(tmp_path, {"not_a_constructor_argument": 1})
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        message = str(exc.value)
        assert "does not accept the declared config" in message
        assert "not_a_constructor_argument" in message

    def test_a_MISSPELLED_config_key_is_refused_rather_than_dropped(self, tmp_path):
        """Seam A's originating defect: ``configs:`` for ``config:`` was
        silently dropped and the family resolved as though nothing had been
        declared."""
        vehicle = materialize_vehicle(tmp_path)
        _rewrite_manifest(vehicle, lambda raw: raw["task_data_path"].update(configs={"a": 1}))
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        message = str(exc.value)
        assert "configs" in message
        assert "refused rather than ignored" in message

    def test_the_composition_names_no_task_specific_key(self, tmp_path):
        """Seam A's task-agnosticism rule, executable: the authority checks a
        SHAPE. A refusal mentioning ``manifest_path`` or ``clips_path`` would
        mean the framework learned a task's constructor arguments."""
        vehicle = self._with_config(tmp_path, {"not_a_constructor_argument": 1})
        with pytest.raises(TaskCompositionError) as exc:
            compose_run_task_bindings(str(vehicle.manifest))
        for task_key in ("manifest_path", "clips_path", "file_index"):
            assert task_key not in str(exc.value)


# ======================================================================
# N8 — parent/child semantic identity mismatch
# ======================================================================


class TestN8ParentChildSemanticIdentityMismatch:
    """§J N8 · failure class: the transport severed or tampered.
    Earliest expected refusal: the child, BEFORE consumption. Evidence: the
    child fails closed naming BOTH facts.

    N2 breaks the ARTIFACT and lets the transport work; N8 breaks the
    TRANSPORT and leaves the artifact alone. They are the same refusal reached
    from opposite directions, and a framework could pass one while failing the
    other — which is why they are separate rows.

    §C.2 again: this targets ``task_data_path``, the family that HAS a parent
    pin. The metric and deliverable-naming families are re-composed child-side
    with none, deliberately.
    """

    def test_a_TAMPERED_identity_is_refused_naming_both_facts(self, tmp_path):
        vehicle = materialize_vehicle(tmp_path)
        parent = run_witness(_PARENT_PIN_WITNESS, str(vehicle.manifest))
        genuine = parent.payload["argv"][3]
        tampered = genuine[:-8] + "deadbeef"

        child = run_witness(_CHILD_WITNESS, str(vehicle.manifest), vehicle.task_id, tampered)
        assert child.returncode == 3, child.stderr
        assert child.payload["error"] == TaskDataPathIdentityError.__name__
        message = child.payload["message"]
        assert tampered in message, "the refusal does not name what the parent claimed"
        assert genuine in message, "the refusal does not name what the child resolved"

    def test_a_MISMATCHED_id_is_refused_naming_both_declarations(self, tmp_path):
        """The other severance: the transported id and the transported
        manifest disagree, so parent and child are reading different
        declarations."""
        vehicle = materialize_vehicle(tmp_path)
        child = run_witness(_CHILD_WITNESS, str(vehicle.manifest), "an_id_nobody_declared", "-")
        assert child.returncode == 3, child.stderr
        assert child.payload["error"] == TaskDataPathResolutionError.__name__
        message = child.payload["message"]
        assert "an_id_nobody_declared" in message
        assert vehicle.task_id in message, (
            "the refusal names only the id the child could not find, not what "
            "the manifest actually declares — an operator cannot tell a typo "
            "from a severed transport"
        )

    def test_a_composed_parent_ALWAYS_emits_the_identity_flag(self, tmp_path):
        """Severance detected at the source. ``identity=None`` is legitimately
        an ABSENCE OF A CLAIM (a pre-C2 parent), so a child cannot distinguish
        'severed' from 'legacy' — which means the guarantee has to live in the
        parent: a composed run always pins."""
        vehicle = materialize_vehicle(tmp_path)
        composition = compose_run_task_bindings(str(vehicle.manifest))
        argv = transport_argv(composition.task_data_path)
        assert TASK_DATA_PATH_IDENTITY_FLAG in argv
        assert argv[argv.index(TASK_DATA_PATH_IDENTITY_FLAG) + 1]

    def test_the_child_that_receives_the_GENUINE_pin_proceeds(self, tmp_path):
        vehicle = materialize_vehicle(tmp_path)
        parent = run_witness(_PARENT_PIN_WITNESS, str(vehicle.manifest))
        child = run_witness(
            _CHILD_WITNESS, str(vehicle.manifest), vehicle.task_id, parent.payload["argv"][3]
        )
        assert child.returncode == 0, child.stderr


# ======================================================================
# N9 / N11 — the two census plants
# ======================================================================


class TestN9AndN11AreCensusPlantsNotRuns:
    """§J N9 and N11 · witness class: **det plant**, evidence: census RED.

    Both are owned by the census module and proven there, per plant, with
    ``count == 1`` and a green baseline. This class exists so the matrix is
    traceable from one place — and so that deleting the census's plants is
    caught here rather than being noticed at the Gate.

    **How this fails**: remove either plant family from the census module and
    the import or the parametrization below goes red.
    """

    def test_N9_the_hidden_fallback_plant_is_owned_and_executable(self):
        from tests.unit.guardrails.test_step12_pr12e_census import find_silent_task_fallback

        planted = find_silent_task_fallback(
            __import__("ast").parse(
                "try:\n    m = compose()\nexcept Exception:\n    m = TIDMAD_METRIC_ID\n"
            )
        )
        assert len(planted) == 1

    def test_N11_the_bypass_plant_is_owned_and_executable(self):
        from tests.unit.guardrails.test_step12_pr12e_census import find_identity_dispatch

        planted = find_identity_dispatch(
            __import__("ast").parse('if task == "a_fourth_task_v0":\n    pass\n'),
            ("a_fourth_task_v0",),
        )
        assert len(planted) == 1


# ======================================================================
# Integration evidence
# ======================================================================


class TestTheControlsRanAgainstTheRealPackage:
    """The row a Gate reads to know whether this matrix is actually discharged.

    Every control above runs against the in-repo mechanism fixture until
    ``SIDERIUS_12E_PACKAGE_ROOT`` binds. That is honest coverage of the
    REFUSAL MECHANISM, and it is not what §J asks for — §J asks for the
    controls executed against the real package. This test SKIPS while unbound
    and asserts the real artifact was used once it is, so "the negative matrix
    is green" can never be reported for a run that only ever saw the fixture.
    """

    def test_the_vehicle_is_the_out_of_tree_package(self, tmp_path):
        if package_root_from_env() is None:
            pytest.skip(
                f"{PACKAGE_ROOT_ENV} unset — N1..N9 are discharged against the "
                f"in-repo mechanism fixture. The real-artifact execution binds "
                f"at the integration checkpoint."
            )
        vehicle = materialize_vehicle(tmp_path)
        assert vehicle.is_real
        assert not str(package_root_from_env()).startswith(str(REPO_ROOT)), (
            "the package is inside the repository, which makes the §I census "
            "self-satisfying and relocation equality untestable (§I.1)"
        )

    def test_the_matrix_this_module_owns_is_N1_to_N9_plus_N11(self):
        """§J's owner column, made auditable from either side.

        N10 (resume against an incompatible package identity) belongs to
        workstream C's restore family; N11 is a census plant proven in the
        census module and traced here. Asserted over the module's DEFINED
        CLASSES rather than over its source text — the first draft searched
        the file for ``"class TestN10"`` and failed on the assertion's own
        string literal, which is the self-referential shape CLAUDE.md forbids
        wearing a census costume.
        """
        owned = {
            int(match.group(1))
            for name in globals()
            if (match := re.match(r"^TestN(\d+)[A-Z]", name))
        }
        # 9 is the census-plant class, which also traces N11 — the two plant
        # rows share one owner because both are proven in the census module.
        assert owned == {1, 2, 3, 4, 5, 6, 7, 8, 9}, owned
        assert "TestN10ResumeIdentity" not in globals(), (
            "N10 is workstream C's; a copy here would be the duplicated-helper defect §G.3 forbids"
        )
        assert "TestN9AndN11AreCensusPlantsNotRuns" in globals()
