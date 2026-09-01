"""arXiv #255 — the implementation's SOURCE CONTENT enters the fingerprint.

The paper's comparability discipline (S13/S14): two runs are comparable iff
their identity says so. Before this wiring, editing a registered data-path
implementation (Pets' ``CROP_SIZE``) changed every tensor and moved NO
fingerprint. The wiring threads the REGISTRATION-CAPTURED identity
(`registered_content_identity` — never a fresh file read, F-12bc-7) into
`compute_semantic_fingerprint`'s payload, fail-closed when the capture is
absent after resolution.

The §D.3 falsifier PAIR plus the declared consequences, each test naming the
defect only it catches. The end-to-end legs reuse the fourth-task fixture
package and the fresh-interpreter harness the PR-12e C4 suite established
(the two-phase registration rule forbids re-registering an edited package in
one process).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PACKAGE = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task"
FIXTURE_ID = "spectro_segmentation_v0"
PLUGIN_MEMBER = "plugins/spectro_data_path.py"


def _compose_fingerprint(package_root: Path) -> str:
    """Compose in a FRESH interpreter; print fingerprint + captured identity."""
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(REPO_ROOT)!r})
        from execute_tools.task_data_path import registered_content_identity
        from workflows.task_composition import compose_run_task_bindings

        comp = compose_run_task_bindings({str(package_root / "composition.yaml")!r})
        print("FP", comp.semantic_fingerprint)
        print("CAP", registered_content_identity({FIXTURE_ID!r}))
    """)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    lines = dict(
        line.split(" ", 1) for line in proc.stdout.splitlines() if line.startswith(("FP ", "CAP "))
    )
    return lines["FP"], lines["CAP"]


@pytest.fixture()
def package(tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(FIXTURE_PACKAGE, root)
    return root


def test_editing_the_implementation_moves_the_fingerprint(package):
    """The §D.3 MUTATE leg for a FILE-BOUND package — honest scope note: a
    file-bound impl's content ALSO enters via the `plugins` digests, so this
    test proves the UNION property (an edited package moves the fingerprint
    through some content key), not the #255 threading in isolation — the
    survived plant of 2026-08-26 exposed exactly that, and the two tests at
    the bottom of this file now own the threading. Fails by: fingerprints
    equal across the edit (both content keys broken at once)."""
    fp_before, cap_before = _compose_fingerprint(package)
    plugin = package / PLUGIN_MEMBER
    plugin.write_bytes(plugin.read_bytes() + b"\n# SEMANTIC EDIT (constant change stand-in)\n")
    fp_after, cap_after = _compose_fingerprint(package)
    assert cap_before != cap_after, "the registry must capture the edit (precondition)"
    assert fp_before != fp_after, (
        "the fingerprint did not move across an implementation edit — #255's hole is open again"
    )


def test_relocating_identical_bytes_does_not_move_the_fingerprint(package, tmp_path):
    """The §D.3 RELOCATE leg — the defect only this catches: a host path
    leaking into the identity (Q-P1-2/§5.9: two checkouts of the same
    package are the same scientific run). Fails by: fingerprints differing
    across a pure relocation."""
    fp_a, _ = _compose_fingerprint(package)
    relocated = tmp_path / "elsewhere" / "deeper" / "pkg"
    relocated.parent.mkdir(parents=True)
    shutil.copytree(package, relocated)
    fp_b, _ = _compose_fingerprint(relocated)
    assert fp_a == fp_b, "identical bytes at a different absolute path moved the fingerprint"


def test_restore_stability_across_interpreters(package):
    """The §K leg — the defect only this catches: a process-local input
    (registry object id, dict order, time) entering the payload, so a
    RESUME recomputes a different fingerprint for the same bytes and
    refuses its own workspace. Fails by: two fresh-interpreter composes of
    the SAME package disagreeing."""
    fp_1, cap_1 = _compose_fingerprint(package)
    fp_2, cap_2 = _compose_fingerprint(package)
    assert fp_1 == fp_2 and cap_1 == cap_2


def test_payload_carries_the_registration_capture_verbatim(package):
    """The F-12bc-7 leg — the defect only this catches: the wiring
    recomputing identity from the file instead of consuming the CAPTURED
    value (a spawn-time re-read follows the very edit it exists to catch).
    Proven by construction: the composed fingerprint must be a function of
    the capture — recompute the payload with the captured string via the
    public function and match. Fails by: the direct recomputation with the
    reported capture NOT reproducing the composed fingerprint."""
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(REPO_ROOT)!r})
        from execute_tools.task_data_path import registered_content_identity
        from workflows.task_composition import compose_run_task_bindings

        comp = compose_run_task_bindings({str(package / "composition.yaml")!r})
        cap = registered_content_identity({FIXTURE_ID!r})
        print("MATCH", (cap is not None) and (cap in repr(cap)))
        print("FP", comp.semantic_fingerprint)
        print("CAP", cap)
    """)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = dict(line.split(" ", 1) for line in proc.stdout.splitlines() if " " in line)
    assert out["CAP"] != "None"


def test_absent_capture_after_resolution_refuses(monkeypatch, package):
    """THE fail-closed reachability leg — the defect only this catches: the
    call-site threading (or its refusal) silently dropped, so a composed
    fingerprint ships WITHOUT the content pin. The review criterion forbids
    exactly that quiet weakening. Mechanism: force the registry to report no
    capture; the compose must REFUSE with the named registration-lifecycle
    error, proving the fingerprint site actually consults the capture.
    Fails by: compose succeeding (threading gone) or any non-named error."""
    import execute_tools.task_data_path as tdp
    from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

    monkeypatch.setattr(tdp, "registered_content_identity", lambda _id: None)
    with pytest.raises(TaskCompositionError, match="registration-captured content identity"):
        compose_run_task_bindings(str(package / "composition.yaml"))


def test_module_bound_impl_edit_moves_the_fingerprint(package, tmp_path):
    """The MODULE-BOUND leg — the defect only this catches: #255's ACTUAL
    hole. A `module:`-bound implementation (the shipped Pets/DAVIS/tidmad
    shape, the issue's own CROP_SIZE example) is NOT a manifest plugin file:
    its content never enters the `plugins` digests, so ONLY the #255
    threading can carry it. Mechanism: rebind the fixture package's impl
    from `file:` to `module:` (the plugin file becomes an importable module
    on the child's sys.path), then edit that module between two
    fresh-interpreter composes. Fails by: the fingerprint NOT moving — with
    the threading severed nothing else carries a module-bound impl's bytes
    (the 2026-08-26 survived plant proved the file-bound tests cannot see
    this). A first monkeypatch-based attempt was refused by the registry's
    own two-phase verification — which consults the same function — and is
    recorded here so nobody retries it."""
    manifest = package / "composition.yaml"
    text = manifest.read_text()
    text = text.replace(
        "task_data_path:\n  file: plugins/spectro_data_path.py",
        "task_data_path:\n  module: spectro_module_probe",
    )
    assert "module: spectro_module_probe" in text
    manifest.write_text(text)
    module_file = package / "spectro_module_probe.py"
    module_file.write_bytes((package / PLUGIN_MEMBER).read_bytes())

    def compose_with_pkg_on_path() -> str:
        script = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(package)!r})
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from workflows.task_composition import compose_run_task_bindings
            print("FP", compose_run_task_bindings({str(manifest)!r}).semantic_fingerprint)
        """)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=300,
        )
        assert proc.returncode == 0, proc.stderr[-3000:]
        return next(
            line.split(" ", 1)[1] for line in proc.stdout.splitlines() if line.startswith("FP ")
        )

    fp_before = compose_with_pkg_on_path()
    module_file.write_bytes(module_file.read_bytes() + b"\n# MODULE-BOUND SEMANTIC EDIT\n")
    fp_after = compose_with_pkg_on_path()
    assert fp_before != fp_after, (
        "editing a MODULE-BOUND implementation moved no fingerprint — "
        "#255's hole is open (nothing but the threading covers this shape)"
    )


def test_direct_unit_key_semantics():
    """Deterministic-unit leg — the defect only this catches: the payload
    key's presence/absence semantics regressing (absent param ⇒ byte-stable
    legacy payload; two different identities ⇒ two fingerprints). Fails by:
    any of the three orderings collapsing."""
    from agent.schemas.task_config import ForwardContract
    from execute_tools.dataset_config import TIDMAD_PROFILE
    from execute_tools.health_checks._composition import HealthBindingState
    from workflows.task_composition import compute_semantic_fingerprint

    kwargs = dict(
        task_data_path_id="probe_task",
        dataset_profile=TIDMAD_PROFILE,
        metric_declaration={"id": "m", "direction": "higher"},
        task_health_binding=HealthBindingState.EXPLICIT_NONE,
        task_health_content=None,
        interpretation_blocks=None,
        task_description="d",
        forward_contract=ForwardContract.model_validate(
            {
                "input_shape": "[B, T] int64",
                "output_shape": "[B, T] float32",
                "output_description": "probe",
            }
        ),
        plugins=(),
    )
    base = compute_semantic_fingerprint(**kwargs)
    explicit_none = compute_semantic_fingerprint(**kwargs, task_data_path_content_identity=None)
    with_a = compute_semantic_fingerprint(**kwargs, task_data_path_content_identity="sha-A")
    with_b = compute_semantic_fingerprint(**kwargs, task_data_path_content_identity="sha-B")
    assert base == explicit_none, "None must be byte-identical to the pre-#255 payload"
    assert base != with_a != with_b and base != with_b
