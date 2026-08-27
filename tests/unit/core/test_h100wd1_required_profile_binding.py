"""F-H100-WD-1-PRETAG — hash-bound fail-closed runtime-profile binding (Route B).

The defect class this file guards: ``resolve_runtime_profile`` fails OPEN on a
missing profile (UNCALIBRATED => watchdog DISABLED), so a formal campaign on
unqualified hardware silently runs with no runaway protection — and nothing
certifies that the overlay a bound run consumes is the one the operator
qualified. The Route-B mechanism (operator-ruled) is a DECLARED
``RequiredProfileBinding`` that refuses loudly instead of falling back.

The mechanism is pre-tag; campaign VALUES (H100 rows, measured numbers) are
post-tag qualification data and appear nowhere in this file. Each test names
the defect only it catches and how it fails when the behavior breaks.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import core.runtime_control.watchdog_profile as watchdog_profile_module
from agent.skills.evaluate_time_skill.calibration import gpu_slug
from core.runtime_control.watchdog_profile import (
    RequiredProfileBinding,
    RequiredProfileBindingError,
    resolve_runtime_profile,
    resolve_watchdog_launch_settings,
)

RTX_5090 = "NVIDIA GeForce RTX 5090"
H100 = "NVIDIA H100 80GB HBM3"

#: Hardcoded expectations for what ``_profile_key`` produces — never computed
#: by calling the module under test.
KEY_5090_SINGLE = "nvidia_geforce_rtx_5090/single"
KEY_H100_QUAD = "nvidia_h100_80gb_hbm3/four_way_coresident"


@pytest.fixture()
def calib_dir(tmp_path, monkeypatch):
    """Point the calibration dir at an empty tmp dir so a developer machine's
    real measured overlay never leaks into these assertions (same isolation
    as test_arxiv_261_watchdog_profile.py)."""
    monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))
    return tmp_path


def _write_overlay(
    calib: Path, device_name: str, profiles: dict[str, dict[str, object]]
) -> tuple[Path, str]:
    """Write a measured overlay and return ``(path, sha256-of-the-exact-bytes)``.

    The digest is computed HERE over the bytes the test wrote — never read
    back from the resolver, so a resolver that hashed the wrong bytes cannot
    self-certify.
    """
    payload = json.dumps({"profiles": profiles}).encode("utf-8")
    path = calib / f"runtime_profiles_{gpu_slug(device_name)}.json"
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


#: The overlay row bound in the certification tests — deliberately different
#: from the shipped 5090/single literals (3.5 / 120), so a fall-through to
#: shipped is DETECTED by value, not only by provenance.
BOUND_ROW = {
    "watchdog_enabled": True,
    "watchdog_safety_factor": 2.25,
    "watchdog_floor_seconds": 90.0,
}


# ---------------------------------------------------------------------------
# (g) DIFFERENTIAL witness — the undeclared path is byte-identical
# ---------------------------------------------------------------------------


def test_differential_undeclared_ladder_is_byte_identical(calib_dir):
    """F-H100-WD-1-PRETAG differential witness — the defect only this catches:
    the Route-B binding mechanism CHANGING the undeclared path. With NO
    binding declared, all three ladder outcomes (measured-hit, shipped-hit,
    uncalibrated) must match the HAND-WRITTEN dicts below, which pin the
    pre-change contract and are recorded PASSING against the pristine module
    before the binding existed (the differential-first workflow). Fails by:
    any field, value, or provenance string moving on the undeclared path.
    """
    # (1) shipped-hit: empty calibration dir, the committed 5090/single row.
    assert resolve_runtime_profile(RTX_5090, "single").model_dump() == {
        "device_name": "NVIDIA GeForce RTX 5090",
        "execution_regime": "single",
        "calibrated": True,
        "watchdog_enabled": True,
        "watchdog_safety_factor": 3.5,
        "watchdog_floor_seconds": 120.0,
        "provenance": "shipped:nvidia_geforce_rtx_5090/single",
    }

    # (2) uncalibrated: a pair in neither layer -> the honest fail-open legacy
    #     triple (watchdog DISABLED; the outer wall-time budgets are the bound).
    assert resolve_runtime_profile(H100, "four_way_coresident").model_dump() == {
        "device_name": "NVIDIA H100 80GB HBM3",
        "execution_regime": "four_way_coresident",
        "calibrated": False,
        "watchdog_enabled": False,
        "watchdog_safety_factor": None,
        "watchdog_floor_seconds": 60.0,
        "provenance": "uncalibrated",
    }

    # (3) measured-hit: an overlay row outranks the shipped row.
    overlay_path, _ = _write_overlay(
        calib_dir,
        RTX_5090,
        {
            KEY_5090_SINGLE: {
                "watchdog_enabled": True,
                "watchdog_safety_factor": 2.0,
                "watchdog_floor_seconds": 90.0,
            }
        },
    )
    assert resolve_runtime_profile(RTX_5090, "single").model_dump() == {
        "device_name": "NVIDIA GeForce RTX 5090",
        "execution_regime": "single",
        "calibrated": True,
        "watchdog_enabled": True,
        "watchdog_safety_factor": 2.0,
        "watchdog_floor_seconds": 90.0,
        "provenance": f"measured:{overlay_path}",
    }


# ---------------------------------------------------------------------------
# (a)-(e) resolve_runtime_profile under a DECLARED binding
# ---------------------------------------------------------------------------


def test_declared_and_matching_binding_certifies_the_overlay_row(calib_dir):
    """(a) F-H100-WD-1-PRETAG — the defect only this catches: the bound path
    resolving anything but the certified overlay row, or stamping provenance
    that does not carry the certified hash (which would make a bound run's
    record unauditable). The sha is computed independently in the test over
    the exact bytes written — never read back from the resolver. Fails by:
    shipped/uncalibrated values leaking in, or provenance not being
    'bound:<path>#sha256=<hex>'."""
    overlay_path, sha = _write_overlay(calib_dir, RTX_5090, {KEY_5090_SINGLE: BOUND_ROW})
    binding = RequiredProfileBinding(
        artifact_path=str(overlay_path), profile_key=KEY_5090_SINGLE, expected_sha256=sha
    )
    profile = resolve_runtime_profile(RTX_5090, "single", required_binding=binding)
    assert profile.calibrated is True
    assert profile.watchdog_enabled is True
    assert profile.watchdog_safety_factor == 2.25
    assert profile.watchdog_floor_seconds == 90.0
    assert profile.provenance.startswith("bound:")
    assert profile.provenance == f"bound:{overlay_path}#sha256={sha}"


def test_declared_binding_with_missing_overlay_refuses_naming_the_path(calib_dir):
    """(b) F-H100-WD-1-PRETAG — the defect only this catches: a declared
    requirement on a machine with NO measured overlay falling open to the
    UNCALIBRATED disabled-watchdog state — the silent fail-open this repair
    removes (shipped even HAS a 5090/single row it could borrow). Fails by:
    resolution returning any RuntimeProfile, or the refusal not naming the
    missing path and the declared identity."""
    missing = calib_dir / f"runtime_profiles_{gpu_slug(RTX_5090)}.json"
    binding = RequiredProfileBinding(
        artifact_path=str(missing), profile_key=KEY_5090_SINGLE, expected_sha256="0" * 64
    )
    with pytest.raises(RequiredProfileBindingError, match="does not exist") as excinfo:
        resolve_runtime_profile(RTX_5090, "single", required_binding=binding)
    message = str(excinfo.value)
    assert str(calib_dir / f"runtime_profiles_{gpu_slug(RTX_5090)}.json") in message
    assert KEY_5090_SINGLE in message


def test_declared_binding_with_tampered_overlay_refuses_carrying_both_digests(calib_dir):
    """(c) F-H100-WD-1-PRETAG — the defect only this catches: silent
    divergence from the declared overlay — the file the run consumes is not
    the file the operator certified (post-qualification edit, partial write,
    wrong box). The sha is captured from the ORIGINAL bytes, then the file
    is modified. Fails by: resolution succeeding from the tampered bytes, or
    the refusal not carrying BOTH digests (declared and actual) for the
    audit trail."""
    overlay_path, certified_sha = _write_overlay(calib_dir, RTX_5090, {KEY_5090_SINGLE: BOUND_ROW})
    binding = RequiredProfileBinding(
        artifact_path=str(overlay_path),
        profile_key=KEY_5090_SINGLE,
        expected_sha256=certified_sha,
    )
    tampered = json.dumps({"profiles": {KEY_5090_SINGLE: {"watchdog_enabled": False}}}).encode(
        "utf-8"
    )
    overlay_path.write_bytes(tampered)
    tampered_sha = hashlib.sha256(tampered).hexdigest()
    assert tampered_sha != certified_sha
    with pytest.raises(RequiredProfileBindingError) as excinfo:
        resolve_runtime_profile(RTX_5090, "single", required_binding=binding)
    message = str(excinfo.value)
    assert certified_sha in message
    assert tampered_sha in message


def test_verified_overlay_lacking_the_required_row_refuses_never_falls_through(calib_dir):
    """(d) F-H100-WD-1-PRETAG — the defect only this catches: a hash-VERIFIED
    overlay that lacks the required row falling through to the ladder. The
    trap is armed: shipped runtime_profiles.yaml DOES carry 5090/single, so
    a fall-through would RETURN a shipped RuntimeProfile and pytest.raises
    would fail with DID NOT RAISE — that is the no-escape assertion. Fails
    by: any RuntimeProfile escaping, or anything but the named refusal."""
    overlay_path, sha = _write_overlay(
        calib_dir, RTX_5090, {"nvidia_geforce_rtx_5090/dual_coresident": BOUND_ROW}
    )
    binding = RequiredProfileBinding(
        artifact_path=str(overlay_path), profile_key=KEY_5090_SINGLE, expected_sha256=sha
    )
    with pytest.raises(RequiredProfileBindingError, match="does not carry"):
        resolve_runtime_profile(RTX_5090, "single", required_binding=binding)


def test_declared_key_mismatching_discovered_pair_refuses_naming_both(calib_dir):
    """(e) F-H100-WD-1-PRETAG — the defect only this catches: a binding
    certified for one (hardware, regime) silently applying on another — the
    cross-device/cross-regime borrowing the profile system exists to forbid,
    now at the binding layer. The identity check must precede any overlay
    read: no overlay exists here, and the refusal must still be the
    mismatch, not the missing file. Fails by: resolution proceeding, the
    refusal not naming BOTH keys, or the missing-file refusal firing
    first."""
    binding = RequiredProfileBinding(
        artifact_path=str(calib_dir / "never_read.json"),
        profile_key=KEY_H100_QUAD,
        expected_sha256="0" * 64,
    )
    with pytest.raises(RequiredProfileBindingError) as excinfo:
        resolve_runtime_profile(RTX_5090, "single", required_binding=binding)
    message = str(excinfo.value)
    assert KEY_H100_QUAD in message
    assert KEY_5090_SINGLE in message
    assert "does not exist" not in message


# ---------------------------------------------------------------------------
# (f) resolve_watchdog_launch_settings under a DECLARED binding
# ---------------------------------------------------------------------------


def test_binding_with_operator_enablement_flag_is_a_loud_contradiction(calib_dir):
    """(f) F-H100-WD-1-PRETAG — the defect only this catches: OPERATOR MODE
    (an explicit --runtime_watchdog/--no_runtime_watchdog) skipping profile
    resolution while a REQUIRED binding stands, leaving the declared
    requirement silently unenforced — the exact fail-open shape this repair
    removes, one layer up. Both flag polarities must refuse. Fails by:
    either polarity returning ResolvedWatchdogSettings ('cli' provenance)
    instead of raising."""
    binding = RequiredProfileBinding(
        artifact_path=str(calib_dir / "never_read.json"),
        profile_key=KEY_5090_SINGLE,
        expected_sha256="0" * 64,
    )
    for flag in (True, False):
        with pytest.raises(RequiredProfileBindingError, match="OPERATOR MODE"):
            resolve_watchdog_launch_settings(
                cli_enabled=flag,
                cli_safety_factor=None,
                cli_floor_seconds=None,
                execution_regime="single",
                device_name=RTX_5090,
                required_binding=binding,
            )


def test_profile_mode_with_binding_yields_bound_settings(calib_dir):
    """(f) F-H100-WD-1-PRETAG — the defect only this catches: PROFILE MODE
    dropping the binding on the floor and resolving through the unbound
    ladder — shipped 3.5/120 would answer here instead of the bound 2.25/90
    — or the bound provenance / profile_calibrated=True not reaching the
    launch record. Also witnesses the ruled boundary: a field-level floor
    override in PROFILE MODE stays legal, because the binding governs WHICH
    profile is consumed, not the recorded per-field launch overrides. Fails
    by: shipped values/provenance appearing, profile_calibrated not True, or
    the field-level override being refused or ignored."""
    overlay_path, sha = _write_overlay(calib_dir, RTX_5090, {KEY_5090_SINGLE: BOUND_ROW})
    binding = RequiredProfileBinding(
        artifact_path=str(overlay_path), profile_key=KEY_5090_SINGLE, expected_sha256=sha
    )

    bound = resolve_watchdog_launch_settings(
        cli_enabled=None,
        cli_safety_factor=None,
        cli_floor_seconds=None,
        execution_regime="single",
        device_name=RTX_5090,
        required_binding=binding,
    )
    assert bound.enabled is True
    assert bound.safety_factor == 2.25
    assert bound.floor_seconds == 90.0
    assert bound.profile_calibrated is True
    assert bound.provenance.startswith(f"bound:{overlay_path}#sha256={sha}")

    floored = resolve_watchdog_launch_settings(
        cli_enabled=None,
        cli_safety_factor=None,
        cli_floor_seconds=200.0,
        execution_regime="single",
        device_name=RTX_5090,
        required_binding=binding,
    )
    assert floored.enabled is True
    assert floored.safety_factor == 2.25
    assert floored.floor_seconds == 200.0
    assert floored.profile_calibrated is True


# ---------------------------------------------------------------------------
# (h) TOCTOU structural witness — hash THE EXACT BYTES PARSED
# ---------------------------------------------------------------------------


def test_bound_loader_structure_hashes_the_exact_bytes_it_parses():
    """(h) F-H100-WD-1-PRETAG — the defect only this catches: someone
    rewriting _load_bound_overlay to hash-then-REOPEN (verify the digest,
    then open()/read_text() the file again to parse), reintroducing the
    TOCTOU window the operator rule forbids — between two reads a swapped
    file is hashed as one content and parsed as another, and every
    behavioral test above stays green because nothing races in-process.
    Structural assertions on the AST of the production source (path derived
    from the imported module's __file__, never hardcoded): exactly ONE
    read_bytes call, ZERO open()/read_text() calls, and json.loads consumes
    the SAME variable hashlib.sha256 consumed. Fails by: a second read
    appearing, or the parse input diverging from the hash input."""
    module_file = watchdog_profile_module.__file__
    assert module_file is not None
    tree = ast.parse(Path(module_file).read_text(encoding="utf-8"), filename=module_file)
    loader = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_load_bound_overlay"
    )

    read_bytes_calls = 0
    forbidden_calls: list[str] = []
    sha_args: list[str] = []
    loads_args: list[str] = []
    for node in ast.walk(loader):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            forbidden_calls.append("open")
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr == "read_bytes":
            read_bytes_calls += 1
        elif func.attr in {"read_text", "open"}:
            forbidden_calls.append(func.attr)
        elif (
            func.attr == "sha256"
            and isinstance(func.value, ast.Name)
            and func.value.id == "hashlib"
        ):
            first = node.args[0] if node.args else None
            assert isinstance(first, ast.Name), "hashlib.sha256 must hash a NAMED bytes object"
            sha_args.append(first.id)
        elif func.attr == "loads" and isinstance(func.value, ast.Name) and func.value.id == "json":
            first = node.args[0] if node.args else None
            assert isinstance(first, ast.Name), "json.loads must parse a NAMED bytes object"
            loads_args.append(first.id)

    assert read_bytes_calls == 1, "the bound loader must read the file EXACTLY once"
    assert forbidden_calls == [], f"re-open/second-read in the bound loader: {forbidden_calls}"
    assert len(sha_args) == 1 and len(loads_args) == 1
    assert sha_args == loads_args, (
        f"json.loads must parse the SAME bytes object hashlib.sha256 hashed; "
        f"got sha256({sha_args[0]}) vs json.loads({loads_args[0]})"
    )


# ---------------------------------------------------------------------------
# (i) DECLARED ARTIFACT PATH — the clause that kills finding_1_invisible_default
#
# Operator ruling (2026-08-26): the landed key+digest binding did NOT resolve
# F-H100-WD-1-PRETAG, because the artifact was still LOCATED by ordinary
# discovery. The binding certified WHAT was found, never that the right file
# was consulted — so an overlay was used because the calibration directory
# happened to contain a file of the expected name. The path is now part of
# the declaration, and the bound branch must never consult discovery.
# ---------------------------------------------------------------------------

#: An artifact row deliberately distinct from BOUND_ROW *and* from the
#: shipped 5090/single literals, so "which file was actually read" is
#: answerable by VALUE and not only by provenance.
DECLARED_ROW = {
    "watchdog_enabled": True,
    "watchdog_safety_factor": 1.75,
    "watchdog_floor_seconds": 45.0,
}


def test_declared_artifact_is_read_instead_of_the_discovered_overlay(calib_dir, tmp_path):
    """(i) The defect only this catches: resolution reading the DISCOVERED
    overlay while a different artifact was declared. This is
    finding_1_invisible_default itself — with both files present and both
    internally valid, only the declared one may be consumed.

    The trap is armed on both sides: the discovery path holds a VALID,
    correctly-keyed overlay carrying BOUND_ROW, so a resolver that consulted
    discovery would find a usable file and would fail certification against
    the declared digest — and a resolver that ignored the path entirely
    would return 2.25/90.0.

    Fails by: the returned values being BOUND_ROW's, provenance naming the
    discovery path, or a refusal (which is what reading the wrong file
    produces once the digests disagree)."""
    discovered_path, discovered_sha = _write_overlay(
        calib_dir, RTX_5090, {KEY_5090_SINGLE: BOUND_ROW}
    )
    qualification = tmp_path / "qualification"
    qualification.mkdir()
    declared_path, declared_sha = _write_overlay(
        qualification, RTX_5090, {KEY_5090_SINGLE: DECLARED_ROW}
    )
    assert declared_path != discovered_path
    assert declared_sha != discovered_sha

    profile = resolve_runtime_profile(
        RTX_5090,
        "single",
        required_binding=RequiredProfileBinding(
            artifact_path=str(declared_path),
            profile_key=KEY_5090_SINGLE,
            expected_sha256=declared_sha,
        ),
    )
    # Read from the DECLARED artifact, by value...
    assert profile.watchdog_safety_factor == 1.75
    assert profile.watchdog_floor_seconds == 45.0
    # ...and the effective artifact identity plus the OBSERVED digest are
    # what is persisted, so a later reader sees what was actually read.
    assert profile.provenance == f"bound:{declared_path}#sha256={declared_sha}"
    assert str(discovered_path) not in profile.provenance
    assert discovered_sha not in profile.provenance


def test_missing_declared_artifact_refuses_even_when_discovery_would_succeed(calib_dir):
    """(i) The defect only this catches: falling back to discovery when the
    DECLARED artifact is absent. The trap is fully armed — the discovery path
    holds a valid overlay carrying the required row, and the binding declares
    THAT FILE'S OWN digest, so a fallback would certify successfully and
    return a RuntimeProfile. Only a resolver that refuses to look anywhere but
    the declared path can raise here.

    Fails by: any RuntimeProfile escaping (pytest.raises reports DID NOT
    RAISE), which is exactly what a discovery fallback produces."""
    _, discovered_sha = _write_overlay(calib_dir, RTX_5090, {KEY_5090_SINGLE: BOUND_ROW})
    absent = calib_dir / "qualification" / "runtime_profiles_h100.json"
    assert not absent.exists()

    with pytest.raises(RequiredProfileBindingError, match="does not exist") as excinfo:
        resolve_runtime_profile(
            RTX_5090,
            "single",
            required_binding=RequiredProfileBinding(
                artifact_path=str(absent),
                profile_key=KEY_5090_SINGLE,
                expected_sha256=discovered_sha,
            ),
        )
    assert str(absent) in str(excinfo.value)


def test_bound_resolution_never_consults_the_discovery_helper():
    """(i) The defect only this catches: the bound branch calling
    ``_measured_overlay_path`` again — for a "sensible default", a fallback,
    or a diagnostic. Any such call re-opens the door finding_1 names, and the
    behavioral tests above cannot see a call whose result is merely logged or
    used only when the declared path is missing.

    Structural assertion on the production AST (module path derived from the
    imported module, never hardcoded). Fails by: the count of
    ``_measured_overlay_path`` calls inside the ``required_binding`` branch
    rising above zero."""
    module_file = watchdog_profile_module.__file__
    assert module_file is not None
    tree = ast.parse(Path(module_file).read_text(encoding="utf-8"), filename=module_file)
    resolver = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_runtime_profile"
    )
    bound_branch = next(
        node
        for node in resolver.body
        if isinstance(node, ast.If)
        and any(
            isinstance(sub, ast.Name) and sub.id == "required_binding"
            for sub in ast.walk(node.test)
        )
    )
    discovery_calls = [
        node
        for node in ast.walk(bound_branch)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_measured_overlay_path"
    ]
    assert discovery_calls == [], (
        "the bound branch must never consult discovery — that is finding_1_invisible_default"
    )


@pytest.mark.parametrize("relative", ["runtime_profiles.json", "qual/x.json", "./x.json"])
def test_relative_artifact_path_is_refused_at_declaration(relative):
    """(i) The defect only this catches: a relative artifact path being
    accepted and later resolved against the CONSUMER's working directory.
    ``run_chain.sh`` cd's to the project dir before exec, so the declaration
    would name a different file than the one qualified — or none — and the
    operator would never learn the two diverged.

    Fails by: construction succeeding for a relative path."""
    with pytest.raises(ValidationError):
        RequiredProfileBinding(
            artifact_path=relative,
            profile_key=KEY_5090_SINGLE,
            expected_sha256="0" * 64,
        )


def test_bound_provenance_records_the_OBSERVED_digest_not_the_declared_one():
    """(i) The defect only this catches: provenance echoing
    ``required_binding.expected_sha256`` instead of the digest computed from
    the bytes actually read.

    NO behavioural test can see this. Certification only succeeds when the
    two are equal, so on every success path the echoed and observed values
    are the same string — an echo is invisible until the day something makes
    them differ, which is precisely the day the record needs to be true. The
    point of the record is what was CONSUMED, not what was asked for.

    Structural assertion on the production AST, the same technique the TOCTOU
    witness above uses and for the same reason. Fails by: the provenance
    f-string interpolating an ``expected_sha256`` attribute, or no longer
    interpolating the loader's returned ``digest``."""
    module_file = watchdog_profile_module.__file__
    assert module_file is not None
    tree = ast.parse(Path(module_file).read_text(encoding="utf-8"), filename=module_file)
    resolver = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_runtime_profile"
    )
    bound_branch = next(
        node
        for node in resolver.body
        if isinstance(node, ast.If)
        and any(
            isinstance(sub, ast.Name) and sub.id == "required_binding"
            for sub in ast.walk(node.test)
        )
    )
    provenance_values = [
        kw.value
        for call in ast.walk(bound_branch)
        if isinstance(call, ast.Call)
        for kw in call.keywords
        if kw.arg == "provenance"
    ]
    assert len(provenance_values) == 1, "expected exactly one bound provenance stamp"
    stamp = provenance_values[0]

    interpolated = {node.id for node in ast.walk(stamp) if isinstance(node, ast.Name)}
    assert "digest" in interpolated, (
        "bound provenance must interpolate the digest COMPUTED from the bytes "
        "read by _load_bound_overlay"
    )
    echoed = [
        node
        for node in ast.walk(stamp)
        if isinstance(node, ast.Attribute) and node.attr == "expected_sha256"
    ]
    assert echoed == [], (
        "bound provenance must record the OBSERVED digest, never echo "
        "required_binding.expected_sha256 — the record answers 'what was "
        "consumed', not 'what was requested'"
    )
