#!/usr/bin/env python
"""Arm symmetry check (#255 exposure determination — launch-blocking).

The two-arm prior-art experiment is valid only if the arms differ in
NOTHING but the declared arm policy. The #255 exposure determination
CONDITIONS launch validity on exactly that, naming the lock-invisible
population knobs (``formal_portion`` / ``formal_train_portion`` /
``formal_eval_portion``) whose asymmetry would silently break arm
comparability without ever touching the invariants lock.

This checker is mechanical. ``campaign_preflight.sh`` captures the band
launcher's ``--dry-run`` output for BOTH arms with otherwise identical
arguments; this script parses each capture at two layers and diffs them:

1. the resolved launch configuration JSON
   (``run_one_iteration.py --print_resolved_launch_config`` — the policy
   fields), and
2. the exact child argv run_chain.sh would exec
   (``[DRY-RUN] would exec`` — where the population knobs actually live:
   the resolved-config JSON does NOT carry ``formal_*`` portions, data
   dir/scope, time budgets or VRAM budgets, so only the argv layer can
   prove them symmetric).

F-SCANG-4 (release blocker) added the third layer, because the first two
are both argv:

3. the ARM SURFACE artifacts (``campaign_arm_surface.py``) — RENDERED
   PROMPT BYTES, the ENVIRONMENT and the MACHINE-LOCAL STORES. The frozen
   row's finding is that layers 1-2 compare "two HYPOTHETICAL COMMAND
   LINES on ONE MACHINE, and every route that actually differs between two
   pods — home-directory stores, environment variables, rendered prompt
   BYTES — is outside what it can see". Layer 3 is REQUIRED, not optional:
   a surface argument the preflight forgets to pass would restore an
   argv-only gate wearing the name of a symmetry gate, which is exactly
   what the row describes.

   Prompt bytes are compared in two states. The NEUTRAL render (both arms
   at ``baseline_isolation=False``) must be byte-identical — it holds the
   treatment constant, so any difference there came from the machine. The
   ARM render must differ on the declared treatment surfaces — two arms
   that render identical prompts are mis-wired, not symmetric.

N-6 (release blocker) added the ATTRIBUTION rule, because layer 3 was
labelling evidence it never verified:

   the label must not claim more than the comparison established.

Two things follow, and both are enforced here rather than by the caller.

*The strength of a sibling surface is DERIVED, never asserted.* The
preflight used to set ``provenance=published`` on ``[ -f <path> ]`` alone,
and the artifact carried no captured-at, no host and no revision for any
reader to check. One same-host rehearsal — or a day-1 publication, which
survives every cold start because the cold-start row globs band workspaces
and never the campaign root — therefore earned the strongest label the
report can print, while the honesty disclaimer was printed ONLY in the
weaker ``local`` state and so DISAPPEARED exactly as the claim strengthened.
Schema v2 makes ``provenance`` required, :func:`classify_comparison` reads
it, and the caller supplies only the one fact it cannot be wrong about:
WHERE it read the file (``--sibling-source``).

*A layer that cannot differ is reported NOT COMPARED, never as agreeing.*
``capture_environment`` and ``resolve_stores`` take no arm argument, so when
both surfaces come from ONE host their environment and machine-local-store
sections are equal BY CONSTRUCTION — as is the NEUTRAL prompt render, whose
whole job is to detect machine-local contamination. The row nonetheless
reported "environment and machine-local stores agree". Those three layers
are now scoped: a DIFFERENCE is still a violation in every state (a
difference can only be a true positive), but AGREEMENT is reported as
evidence only when the two surfaces were captured on different hosts. The
ARM render is arm-comparable on one host — it tests the treatment wiring,
not the machine — and stays COMPARED always, as do the two argv layers.

Fields that may legitimately differ are the EXPLICIT allowlists below
(#255: arm label, lit-review enable/config — the root-paper variant
rides the lit-review config sha — and baseline isolation, plus the
arm-DERIVED workspace/run_name naming, which is asserted to match its
exact derivation rather than waved through). Every other difference is a
failure, printed field by field. The expected asymmetries are ALSO
asserted — two arms that resolve identically are mis-wired, not
symmetric.

Output-type pin: NO operator knob exists on the un-composed path (S9
audit: ``ProposalOutput.output_type`` is LLM-authored,
``agent/schemas/proposal.py:1120``; no ``WorkflowLaunchConfig`` field, no
chain flag). The check therefore asserts NEITHER argv carries an
output-type token, so a future asymmetric injection fails here.

Exit 0 = symmetric (report printed); exit 1 = violation (field-by-field
diff printed); exit 2 = a capture or surface could not be parsed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

# --- #255 allowlists: the ONLY fields the two arms may differ in -----------

#: Resolved-config JSON keys that express the declared arm policy.
POLICY_KEYS_ALLOWED_TO_DIFFER = {
    "experiment_arm",  # the opaque arm label (ruling R2)
    "lit_review_enabled",  # the experiment's single variable
    "lit_review_config_path",  # follows lit_review_enabled (None when OFF)
    "lit_review_config_sha256",  # carries the root-paper variant identity
    "baseline_isolation",  # the WITHOUT arm's behaviour flag (ruling R6)
}

#: Resolved-config keys that are arm-DERIVED NAMING, not policy: they must
#: differ, but only by the exact campaign derivation asserted below.
NAMING_KEYS = {"workspace", "run_name"}

#: Child-argv flags that express the same arm policy on the wire.
ARGV_FLAGS_ALLOWED_TO_DIFFER = {
    "--ml_lit_review_enabled",
    "--no-ml_lit_review_enabled",
    "--experiment_arm",
    "--baseline_isolation",
    "--workspace",
    "--run_name",
}

#: The #255-named population knobs plus the other launch-blocking surfaces,
#: reported row-by-row even when symmetric (the launch packet wants to SEE
#: them, not infer them from silence).
FORBIDDEN_DIFF_SPOTLIGHT = (
    "--formal_portion",
    "--formal_train_portion",
    "--formal_eval_portion",
    "--data_dir",
    "--data_scope",
    "--health_gate_files",
    "--trial_time_budget_minutes",
    "--formal_time_budget_minutes",
    "--trial_vram_budget_gb",
    "--formal_vram_budget_gb",
    "--gpu_pair_ceiling_gib",
)

ARMS = ("with-prior-art", "without-prior-art")

# --- F-SCANG-4 layer 3: the declared surface-symmetry policy ---------------

#: The artifact shape this checker knows how to read. A surface written by
#: a different schema is refused (exit 2) rather than compared field-blind.
#: v2 (N-6) is v1 plus the REQUIRED ``provenance`` section — a v1 artifact
#: is unattributable, and a stale one already sitting in a campaign root
#: must be refused rather than silently read as another pod's evidence.
SURFACE_SCHEMA = "campaign_arm_surface/v2"

#: Provenance keys a readable surface must carry. Absent -> exit 2.
PROVENANCE_KEYS = ("captured_at", "captured_at_epoch", "host", "project_dir", "revision")

# --- N-6: the layers, and what each one can speak for ----------------------

LAYER_ARGV = "resolved-config + child argv"
LAYER_PROMPT_ARM = "prompt bytes / arm render (declared treatment wiring)"
LAYER_PROMPT_NEUTRAL = "prompt bytes / neutral render (machine contamination)"
LAYER_ENVIRONMENT = "environment"
LAYER_STORES = "machine-local stores"

#: Every layer, in report order.
LAYERS = (LAYER_ARGV, LAYER_PROMPT_ARM, LAYER_PROMPT_NEUTRAL, LAYER_ENVIRONMENT, LAYER_STORES)

#: Layers whose AGREEMENT is evidence only when the two surfaces were
#: captured on DIFFERENT hosts. ``capture_environment`` and
#: ``resolve_stores`` take no arm argument and the neutral render holds the
#: treatment constant, so on one host all three are equal by construction.
CROSS_POD_ONLY_LAYERS = frozenset({LAYER_PROMPT_NEUTRAL, LAYER_ENVIRONMENT, LAYER_STORES})

#: The derived evidence states, strongest to weakest. Determined in this
#: order: an unreadable provenance beats everything, then a code-revision
#: split, then a same-host capture, then staleness.
EVIDENCE_CROSS_POD_VERIFIED = "cross_pod_verified"
EVIDENCE_CROSS_POD_STALE = "cross_pod_stale"
EVIDENCE_SAME_HOST = "same_host"
EVIDENCE_REVISION_MISMATCH = "revision_mismatch"
EVIDENCE_UNVERIFIABLE = "unverifiable"

#: How old a surface may be before its cross-pod claim is downgraded. A
#: preflight runs shortly before a launch; an artifact older than this
#: describes a machine state nobody has re-measured, and the campaign root
#: is not swept by the cold-start row. Staleness DOWNGRADES the label; it is
#: not itself a violation, because an old surface that still agrees is not
#: evidence of asymmetry.
DEFAULT_SIBLING_MAX_AGE_HOURS = 24

#: How far a surface may be dated in the FUTURE before the freshness
#: judgement is abandoned. Two pods rarely share an NTP source to the
#: second; they should share it to the minute.
CLOCK_SKEW_TOLERANCE_SECONDS = 600

#: Where the caller READ the sibling surface. This is the ONE input the
#: caller supplies, because it is the one fact only the caller knows and
#: cannot be wrong about; every strength judgement is derived from the
#: surfaces themselves. ``local`` is the default: forgetting the argument
#: must yield the WEAKEST claim, never the strongest.
SIBLING_SOURCES = ("published", "local")

#: Prompt surfaces whose ARM render MUST differ between the arms. These are
#: exactly the surfaces arXiv U3 (#260, ruling R6) makes isolation-sensitive:
#: ``render_available_models`` swaps the header and drops the built-in branch,
#: and ``load_stage_prompt`` substitutes neutral example literals for the
#: shipped ``wavenet`` / ``5.57`` tokens — which reaches every stage template
#: (comparison and causal carry the literals; the proposing stage embeds the
#: models block). Stated POSITIVELY: a capture that does not contain all of
#: these ids fails, so a renamed or dropped surface cannot quietly shrink the
#: treatment the gate is able to see.
PROMPT_SURFACES_MUST_DIFFER = frozenset(
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

#: Environment variables that MAY differ between the two arms, each with the
#: authority that makes it legitimate. EVERYTHING ELSE captured is
#: arm-invariant and a difference FAILS: an unknown SIDERIUS_* export that
#: differs between pods is precisely the failure class this layer exists for,
#: so the default is fail-closed, not allow-by-omission.
ENVIRONMENT_ARM_LOCAL = {
    # The campaign assigns GPU A to one arm and GPU B to the other
    # (campaign_preflight.sh header, h100_posture.env).
    "CUDA_VISIBLE_DEVICES": "the campaign assigns one card per arm",
    # {root}/{arm}_band{band} — arm-derived by construction.
    "SIDERIUS_CHAIN_WORKSPACE": "the per-chain workspace is arm-derived",
    # Preflight R1c requires a FRESH, campaign-owned root; a per-arm root is
    # what keeps one arm's promoted capabilities out of the other's proposer.
    # Its CONTENT symmetry is checked in machine_local_stores instead.
    "SIDERIUS_GENERATED_LIBRARY_DIR": "per-arm root; content symmetry checked as a store",
    # Per-device learned k-tables; R8 item6 RETAINs this store by design.
    "SIDERIUS_CALIBRATION_DIR": "per-device calibration store (R8 item6 RETAIN)",
    "SIDERIUS_LIVE_CALIBRATION_DIR": "per-device calibration store (R8 item6 RETAIN)",
}

#: Machine-local stores whose CONTENT must be identical across arms. All
#: three reach a prompt: the generated library and the checkout capability
#: state are rendered into ``available_models_block`` /
#: ``available_losses_block``, and the root-paper cache feeds the WITH arm's
#: expert context.
STORE_SYMMETRY_REQUIRED = frozenset(
    {"generated_library", "checkout_capability_state", "root_papers_cache"}
)

#: Recorded and printed, but NOT required symmetric — and this is a
#: deliberate, narrow exemption, not an oversight. The calibration store
#: holds per-device measured k-tables that two different cards SHOULD
#: disagree about, and the cold-start checklist RETAINs it by design (R8
#: item6). It reaches the watchdog, never a prompt.
STORE_SYMMETRY_OBSERVED = frozenset({"calibration_store"})


def _load_surface(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        surface = json.load(handle)
    if not isinstance(surface, dict):
        raise ValueError(f"{path}: surface did not parse to an object")
    schema = surface.get("schema")
    if schema != SURFACE_SCHEMA:
        raise ValueError(f"{path}: unknown surface schema {schema!r} (expected {SURFACE_SCHEMA!r})")
    for section in ("arm", "prompt_bytes", "environment", "machine_local_stores", "provenance"):
        if section not in surface:
            raise ValueError(f"{path}: surface is missing the {section!r} section")
    provenance = surface["provenance"]
    if not isinstance(provenance, dict):
        raise ValueError(f"{path}: 'provenance' is not an object")
    absent = sorted(set(PROVENANCE_KEYS) - set(provenance))
    if absent:
        raise ValueError(
            f"{path}: provenance is missing {absent} — an unattributable surface cannot be "
            "read as another pod's evidence"
        )
    return surface


def check_prompt_bytes(surfaces: dict[str, dict]) -> dict[str, list[str]]:
    """Layer 3a — RENDERED PROMPT BYTES, the route argv cannot express.

    Returned per LAYER, because the two render states answer different
    questions and are not comparable in the same circumstances: the ARM
    render tests the treatment WIRING and is meaningful on one host, while
    the NEUTRAL render is the machine-contamination detector and can only
    speak when the two surfaces come from two machines.
    """
    arm_problems: list[str] = []
    neutral_problems: list[str] = []
    prompts = {arm: surfaces[arm]["prompt_bytes"] for arm in ARMS}

    ids = sorted(set(prompts[ARMS[0]]) | set(prompts[ARMS[1]]))
    if not ids:
        return {
            LAYER_PROMPT_ARM: [
                "prompt-bytes: the surfaces carry no rendered prompt at all — nothing was compared"
            ],
            LAYER_PROMPT_NEUTRAL: [],
        }

    missing = sorted(PROMPT_SURFACES_MUST_DIFFER - set(ids))
    if missing:
        arm_problems.append(
            f"prompt-bytes: declared treatment surface(s) absent from the capture: {missing} — "
            "the gate cannot see the treatment it is supposed to verify"
        )

    for surface_id in ids:
        a, b = prompts[ARMS[0]].get(surface_id), prompts[ARMS[1]].get(surface_id)
        if a is None or b is None:
            side = ARMS[0] if a is None else ARMS[1]
            arm_problems.append(f"prompt-bytes {surface_id}: absent from the {side} surface")
            continue
        # The NEUTRAL render holds the treatment constant, so a difference
        # here is machine-local or environmental contamination reaching the
        # model — the exact route the row says the gate cannot see.
        if a["neutral"] != b["neutral"]:
            neutral_problems.append(
                f"prompt-bytes {surface_id}: the NEUTRAL render differs "
                f"({ARMS[0]}={a['neutral']['sha256'][:12]}… {a['neutral']['bytes']}B, "
                f"{ARMS[1]}={b['neutral']['sha256'][:12]}… {b['neutral']['bytes']}B) — "
                "with the treatment held identical, only machine-local state can do this"
            )
        if surface_id in PROMPT_SURFACES_MUST_DIFFER and a["arm"] == b["arm"]:
            arm_problems.append(
                f"prompt-bytes {surface_id}: IDENTICAL across arms "
                f"({a['arm']['sha256'][:12]}…) but this surface carries the declared "
                "treatment and MUST differ — the arms are mis-wired, not symmetric"
            )
    return {LAYER_PROMPT_ARM: arm_problems, LAYER_PROMPT_NEUTRAL: neutral_problems}


def check_environment(surfaces: dict[str, dict]) -> list[str]:
    """Layer 3b — the ENVIRONMENT, compared name by name, fail-closed."""
    problems: list[str] = []
    envs = {arm: surfaces[arm]["environment"] for arm in ARMS}
    for name in sorted(set(envs[ARMS[0]]) | set(envs[ARMS[1]])):
        if name in ENVIRONMENT_ARM_LOCAL:
            continue
        a = envs[ARMS[0]].get(name)
        b = envs[ARMS[1]].get(name)
        if a != b:
            problems.append(
                f"environment {name}: {ARMS[0]}={a!r} {ARMS[1]}={b!r} — "
                "not a declared arm-local variable"
            )
    return problems


def check_machine_local_stores(surfaces: dict[str, dict]) -> list[str]:
    """Layer 3c — the MACHINE-LOCAL STORES, by content digest."""
    problems: list[str] = []
    stores = {arm: surfaces[arm]["machine_local_stores"] for arm in ARMS}
    classified = STORE_SYMMETRY_REQUIRED | STORE_SYMMETRY_OBSERVED
    seen = set(stores[ARMS[0]]) | set(stores[ARMS[1]])
    unclassified = sorted(seen - classified)
    if unclassified:
        problems.append(
            f"machine-local stores: {unclassified} are captured but not classified as "
            "required-symmetric or observed — classify them before launching"
        )
    absent = sorted(classified - seen)
    if absent:
        problems.append(
            f"machine-local stores: declared store(s) {absent} missing from the capture — "
            "an unmeasured store is not a symmetric one"
        )
    for store_id in sorted(STORE_SYMMETRY_REQUIRED & seen):
        a = stores[ARMS[0]].get(store_id, {})
        b = stores[ARMS[1]].get(store_id, {})
        for arm, entry in ((ARMS[0], a), (ARMS[1], b)):
            if entry.get("error"):
                problems.append(f"machine-local store {store_id} [{arm}]: {entry['error']}")
        if a.get("error") or b.get("error"):
            continue
        if a.get("content_sha256") != b.get("content_sha256"):
            problems.append(
                f"machine-local store {store_id}: content differs "
                f"({ARMS[0]}={a.get('content_sha256', '<absent>')!s:.12}… "
                f"{a.get('entry_count')} entries, "
                f"{ARMS[1]}={b.get('content_sha256', '<absent>')!s:.12}… "
                f"{b.get('entry_count')} entries) — this store reaches the prompt surface"
            )
    return problems


def classify_comparison(
    with_surface: dict,
    without_surface: dict,
    *,
    now_epoch: float,
    max_age_hours: int = DEFAULT_SIBLING_MAX_AGE_HOURS,
) -> dict:
    """What the two surfaces' OWN provenance entitles the report to claim.

    Derived, never asserted. Returns the hosts, the revisions, the age of
    the OLDER surface (symmetric, so both arms' preflights agree), whether
    the cross-pod-only layers are comparable at all, and the resulting
    ``evidence_state``.
    """
    prov = {
        ARMS[0]: with_surface.get("provenance", {}),
        ARMS[1]: without_surface.get("provenance", {}),
    }
    hosts = {arm: prov[arm].get("host") for arm in ARMS}
    revisions = {arm: prov[arm].get("revision") for arm in ARMS}
    epochs = {arm: prov[arm].get("captured_at_epoch") for arm in ARMS}

    unverifiable = not all(hosts.values()) or not all(
        isinstance(epochs[arm], int | float) for arm in ARMS
    )
    revision_known = all(revisions.values())
    same_host = (not unverifiable) and hosts[ARMS[0]] == hosts[ARMS[1]]
    ages = [int(now_epoch - float(epochs[arm])) for arm in ARMS] if not unverifiable else []
    # Reported: the OLDEST surface (symmetric, so both arms' preflights
    # derive the same state).
    age_seconds = max(ages) if ages else None
    # Judged: BOTH ends. A freshness gate that tests only the old direction
    # is bypassed by a clock — a surface stamped next year never expires —
    # and the max() above would hide it behind whichever surface is older.
    # Two pods whose clocks disagree by more than the skew tolerance cannot
    # be compared on recency at all, so neither earns the verified label.
    stale = bool(ages) and (
        max(ages) > max_age_hours * 3600 or min(ages) < -CLOCK_SKEW_TOLERANCE_SECONDS
    )

    if unverifiable or not revision_known:
        state = EVIDENCE_UNVERIFIABLE
    elif revisions[ARMS[0]] != revisions[ARMS[1]]:
        state = EVIDENCE_REVISION_MISMATCH
    elif same_host:
        state = EVIDENCE_SAME_HOST
    elif stale:
        state = EVIDENCE_CROSS_POD_STALE
    else:
        state = EVIDENCE_CROSS_POD_VERIFIED

    return {
        "evidence_state": state,
        "hosts": hosts,
        "revisions": revisions,
        "same_host": same_host,
        "age_seconds": age_seconds,
        "stale": stale,
        "max_age_hours": max_age_hours,
        # The cross-pod-only layers can speak ONLY from two machines whose
        # provenance is readable. Everything else forfeits their agreement.
        "cross_pod_layers_comparable": state
        in (EVIDENCE_CROSS_POD_VERIFIED, EVIDENCE_CROSS_POD_STALE),
    }


def check_provenance(scope: dict) -> list[str]:
    """Violations the provenance itself proves.

    Only ONE: two surfaces rendered by different code revisions are
    comparing two RENDERERS, not two machines, so every prompt-byte verdict
    below them is meaningless. R2 already requires one SHA per campaign, and
    the module docstring's "both arms run from THIS checkout" is exactly
    this assumption made explicit. Staleness and same-host capture are NOT
    violations — they downgrade the claim, which the report states.
    """
    if scope["evidence_state"] != EVIDENCE_REVISION_MISMATCH:
        return []
    return [
        f"provenance revision: {ARMS[0]}={scope['revisions'][ARMS[0]]!r} "
        f"{ARMS[1]}={scope['revisions'][ARMS[1]]!r} — the two surfaces were rendered by "
        "DIFFERENT code, so their prompt bytes compare two renderers rather than two "
        "machines; a campaign must be attributable to one SHA (preflight R2)"
    ]


def check_surfaces_by_layer(
    with_surface: dict,
    without_surface: dict,
    *,
    scope: dict | None = None,
) -> dict[str, list[str]]:
    """Every layer-3 violation, keyed by LAYER. Empty lists = no violation.

    A layer's verdict — compared / not compared — is a separate question,
    answered by :func:`layer_verdicts`. This function reports DIFFERENCES,
    and a difference is a true positive in every state: scoping must never
    silence one, only withhold the claim that agreement proves something.
    """
    surfaces = {ARMS[0]: with_surface, ARMS[1]: without_surface}
    by_layer: dict[str, list[str]] = {layer: [] for layer in LAYERS}
    pairing: list[str] = []
    for arm in ARMS:
        declared = surfaces[arm].get("arm")
        if declared != arm:
            pairing.append(
                f"surface: the {arm} slot carries a surface labelled {declared!r} — "
                "the two captures were paired wrongly"
            )
    if pairing:
        by_layer[LAYER_PROMPT_ARM] = pairing
        return by_layer
    prompt_layers = check_prompt_bytes(surfaces)
    by_layer[LAYER_PROMPT_ARM] = prompt_layers[LAYER_PROMPT_ARM]
    by_layer[LAYER_PROMPT_NEUTRAL] = prompt_layers[LAYER_PROMPT_NEUTRAL]
    by_layer[LAYER_ENVIRONMENT] = check_environment(surfaces)
    by_layer[LAYER_STORES] = check_machine_local_stores(surfaces)
    if scope is not None:
        by_layer[LAYER_PROMPT_ARM] = check_provenance(scope) + by_layer[LAYER_PROMPT_ARM]
    return by_layer


def _not_compared_reason(scope: dict) -> str:
    """Why a cross-pod-only layer could not speak, NAMED per state.

    One generic sentence would be wrong in two of the three states, and a
    row that explains a verdict with the wrong reason is the same class of
    over-claim as a label the comparison never earned.
    """
    state = scope["evidence_state"]
    if state == EVIDENCE_SAME_HOST:
        return (
            "both surfaces were captured on ONE host, and this layer is captured with no arm "
            "argument, so it agrees by construction"
        )
    if state == EVIDENCE_REVISION_MISMATCH:
        return (
            "the two surfaces were rendered by different code revisions, so nothing measured "
            "under them is attributable to the machine rather than the renderer"
        )
    return (
        "at least one surface carries no readable host or capture time, so it cannot be "
        "established that these values came from two different machines"
    )


def layer_verdicts(by_layer: dict[str, list[str]], scope: dict) -> list[tuple[str, str, str]]:
    """``(verdict, layer, why)`` for every layer, in report order.

    The N-6 rule, in three lines of policy:

    * a layer with a DIFFERENCE is ``FAILED`` — always, in every state;
    * a layer with no difference is ``COMPARED`` only if it COULD have
      differed;
    * otherwise it is ``NOT COMPARED``, which is a named absence and not a
      pass. This codebase already spells that ``inapplicable``.
    """
    rows: list[tuple[str, str, str]] = []
    comparable = scope["cross_pod_layers_comparable"]
    for layer in LAYERS:
        if by_layer.get(layer):
            rows.append(("FAILED", layer, f"{len(by_layer[layer])} violation(s), listed below"))
        elif layer in CROSS_POD_ONLY_LAYERS and not comparable:
            rows.append(("NOT COMPARED", layer, _not_compared_reason(scope)))
        else:
            rows.append(("COMPARED", layer, "no difference, and a difference was possible"))
    return rows


def check_surfaces(with_surface: dict, without_surface: dict) -> list[str]:
    """Every layer-3 violation, flattened. Empty = no difference found.

    Kept as the difference-only view: callers that want the per-layer
    verdicts (what was actually COMPARED) use
    :func:`check_surfaces_by_layer` with :func:`layer_verdicts`.
    """
    by_layer = check_surfaces_by_layer(with_surface, without_surface)
    return [problem for layer in LAYERS for problem in by_layer[layer]]


def surface_rows(with_surface: dict, without_surface: dict) -> list[str]:
    """The layer-3 report, printed even when symmetric (as the launch packet
    wants it SEEN, not inferred from silence)."""
    surfaces = {ARMS[0]: with_surface, ARMS[1]: without_surface}
    rows: list[str] = []
    prompts = {arm: surfaces[arm]["prompt_bytes"] for arm in ARMS}
    for surface_id in sorted(set(prompts[ARMS[0]]) | set(prompts[ARMS[1]])):
        a = prompts[ARMS[0]].get(surface_id, {})
        b = prompts[ARMS[1]].get(surface_id, {})
        neutral = "SYMMETRIC" if a.get("neutral") == b.get("neutral") else "DIFF"
        arm_state = "differs" if a.get("arm") != b.get("arm") else "identical"
        rows.append(f"  neutral={neutral:9s} arm={arm_state:9s} {surface_id}")
    stores = {arm: surfaces[arm]["machine_local_stores"] for arm in ARMS}
    for store_id in sorted(set(stores[ARMS[0]]) | set(stores[ARMS[1]])):
        a = stores[ARMS[0]].get(store_id, {})
        b = stores[ARMS[1]].get(store_id, {})
        policy = "REQUIRED " if store_id in STORE_SYMMETRY_REQUIRED else "observed "
        state = "SYMMETRIC" if a.get("content_sha256") == b.get("content_sha256") else "DIFF"
        rows.append(
            f"  {policy}{state:9s} store {store_id}: "
            f"{a.get('entry_count')} / {b.get('entry_count')} entries"
        )
    envs = {arm: surfaces[arm]["environment"] for arm in ARMS}
    names = sorted(set(envs[ARMS[0]]) | set(envs[ARMS[1]]))
    rows.append(
        f"  environment: {len(names)} captured name(s), {len(ENVIRONMENT_ARM_LOCAL)} declared arm-local"
    )
    return rows


def provenance_rows(scope: dict, sibling_source: str) -> list[str]:
    """WHO captured each surface, WHEN and from WHICH CODE — printed in
    EVERY state, because the caveat must not weaken as the label
    strengthens. Under N-6 the disclaimer used to be printed only for the
    weakest state and vanished on the upgrade."""
    age = scope["age_seconds"]
    age_text = "unknown" if age is None else f"{age // 3600}h{(age % 3600) // 60:02d}m"
    return [
        f"  sibling-source : {sibling_source} (where the caller READ the sibling surface)",
        f"  evidence-state : {scope['evidence_state']} (derived from the surfaces' own provenance)",
        f"  hosts          : {ARMS[0]}={scope['hosts'][ARMS[0]]!r} "
        f"{ARMS[1]}={scope['hosts'][ARMS[1]]!r}",
        f"  revisions      : {ARMS[0]}={scope['revisions'][ARMS[0]]!r} "
        f"{ARMS[1]}={scope['revisions'][ARMS[1]]!r}",
        f"  oldest capture : {age_text} ago (downgrade threshold "
        f"{scope['max_age_hours']}h; stale={scope['stale']})",
    ]


def extract_resolved_config(text: str) -> dict:
    """The one resolved-config JSON object out of a launcher dry-run capture."""
    marker = text.find("resolved launch configuration:")
    start = marker if marker >= 0 else 0
    idx = text.find("\n{", start)
    idx = idx + 1 if idx >= 0 else text.index("{", start)
    obj, _ = json.JSONDecoder().raw_decode(text[idx:])
    if not isinstance(obj, dict):
        raise ValueError("resolved config did not parse to an object")
    return obj


def extract_child_argv(text: str) -> list[str]:
    """The run_one_iteration.py argv from run_chain.sh's dry-run print.

    ``submit_iteration_lilab`` prints ``[DRY-RUN] would exec from <dir>:``
    and then one ``%q``-quoted line. The campaign flags are plain tokens
    (no whitespace), so whitespace splitting is exact for them; an exotic
    quoted value would still diff symmetrically on both sides.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "[DRY-RUN] would exec" in line and i + 1 < len(lines):
            tokens = lines[i + 1].split()
            for j, tok in enumerate(tokens):
                if tok.endswith("run_one_iteration.py"):
                    return tokens[j + 1 :]
            return tokens
    raise ValueError("no '[DRY-RUN] would exec' argv line found in the capture")


def argv_pairs(tokens: list[str]) -> dict[str, list[str]]:
    """``--flag VALUE...`` -> {flag: [values]}; a bare switch -> ["<set>"].

    Multi-value flags (``--seed_paths``) collect every following
    non-flag token; a repeated flag extends its list, so a duplicated
    token cannot hide the first occurrence.
    """
    out: dict[str, list[str]] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("--"):
            i += 1
            continue
        values: list[str] = []
        j = i + 1
        while j < len(tokens) and not tokens[j].startswith("--"):
            values.append(tokens[j])
            j += 1
        out.setdefault(tok, []).extend(values if values else ["<set>"])
        i = j
    return out


def check(
    with_text: str,
    without_text: str,
    *,
    workspace_root: str,
    band: str,
) -> list[str]:
    """Every symmetry violation, as printable rows. Empty = symmetric."""
    problems: list[str] = []

    cfg = {
        "with-prior-art": extract_resolved_config(with_text),
        "without-prior-art": extract_resolved_config(without_text),
    }
    argv = {
        "with-prior-art": argv_pairs(extract_child_argv(with_text)),
        "without-prior-art": argv_pairs(extract_child_argv(without_text)),
    }

    # ---- layer 1: resolved-config JSON ------------------------------------
    all_keys = sorted(set(cfg[ARMS[0]]) | set(cfg[ARMS[1]]))
    for key in all_keys:
        a, b = cfg[ARMS[0]].get(key), cfg[ARMS[1]].get(key)
        if a == b:
            if key in POLICY_KEYS_ALLOWED_TO_DIFFER and key != "lit_review_config_path":
                problems.append(
                    f"resolved-config {key}: IDENTICAL ({a!r}) but this is an arm-policy "
                    f"field that MUST differ — the arms are mis-wired, not symmetric"
                )
            continue
        if key in NAMING_KEYS:
            continue  # asserted against the exact derivation below
        if key not in POLICY_KEYS_ALLOWED_TO_DIFFER:
            problems.append(f"resolved-config {key}: with={a!r} without={b!r} — NOT arm policy")

    # The expected policy asymmetry, stated positively.
    expectations = (
        ("experiment_arm", "with-prior-art", "without-prior-art"),
        ("lit_review_enabled", True, False),
        ("baseline_isolation", False, True),
    )
    for key, want_with, want_without in expectations:
        got = (cfg[ARMS[0]].get(key), cfg[ARMS[1]].get(key))
        if got != (want_with, want_without):
            problems.append(
                f"resolved-config {key}: expected with={want_with!r} without={want_without!r}, "
                f"got with={got[0]!r} without={got[1]!r}"
            )

    # Arm-derived naming must be exactly the campaign derivation.
    root = workspace_root.rstrip("/")
    for arm in ARMS:
        want_run_name = f"{arm}_band{band}"
        want_ws_suffix = f"{root}/{want_run_name}"
        if cfg[arm].get("run_name") != want_run_name:
            problems.append(
                f"resolved-config run_name[{arm}]: {cfg[arm].get('run_name')!r} != "
                f"expected derivation {want_run_name!r}"
            )
        ws = str(cfg[arm].get("workspace") or "")
        if not ws.endswith(want_ws_suffix):
            problems.append(
                f"resolved-config workspace[{arm}]: {ws!r} does not end with the "
                f"expected derivation {want_ws_suffix!r}"
            )

    # ---- layer 2: child argv ----------------------------------------------
    all_flags = sorted(set(argv[ARMS[0]]) | set(argv[ARMS[1]]))
    for flag in all_flags:
        a, b = argv[ARMS[0]].get(flag), argv[ARMS[1]].get(flag)
        if a == b:
            continue
        if flag in ARGV_FLAGS_ALLOWED_TO_DIFFER:
            continue
        problems.append(f"child-argv {flag}: with={a!r} without={b!r} — NOT arm policy")

    for flag, arm_present, arm_absent in (
        ("--ml_lit_review_enabled", ARMS[0], ARMS[1]),
        ("--no-ml_lit_review_enabled", ARMS[1], ARMS[0]),
        ("--baseline_isolation", ARMS[1], ARMS[0]),
    ):
        if flag not in argv[arm_present]:
            problems.append(f"child-argv {flag}: missing from the {arm_present} arm")
        if flag in argv[arm_absent]:
            problems.append(f"child-argv {flag}: present on the {arm_absent} arm")

    # Output-type (arXiv #259): the knob EXISTS now (--allowed_output_types;
    # the S9-audit-era "no knob" rule is superseded by the same lane's #259
    # implementation). The constraint is a RUN property, so it must be
    # IDENTICAL across arms: present-in-one-only or differing values is the
    # asymmetric injection this check exists to catch. Both-absent stays
    # legal (an unconstrained non-campaign launch).
    ot_vals = {arm: argv[arm].get("--allowed_output_types") for arm in ARMS}
    if ot_vals[ARMS[0]] != ot_vals[ARMS[1]]:
        problems.append(
            "child-argv --allowed_output_types: asymmetric between arms "
            f"({ARMS[0]}={ot_vals[ARMS[0]]!r}, {ARMS[1]}={ot_vals[ARMS[1]]!r}) — "
            "the output-type constraint is a run property and must be identical"
        )

    return problems


def spotlight_rows(with_text: str, without_text: str) -> list[str]:
    argv_with = argv_pairs(extract_child_argv(with_text))
    argv_without = argv_pairs(extract_child_argv(without_text))
    rows = []
    for flag in FORBIDDEN_DIFF_SPOTLIGHT:
        a, b = argv_with.get(flag), argv_without.get(flag)
        state = "SYMMETRIC" if a == b else "DIFF"
        rows.append(f"  {state:9s} {flag}: with={a!r} without={b!r}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-output", required=True, help="captured WITH-arm dry-run output")
    parser.add_argument(
        "--without-output", required=True, help="captured WITHOUT-arm dry-run output"
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--band", required=True)
    # REQUIRED, not optional (F-SCANG-4). An optional third layer is one the
    # caller can forget, and a forgotten layer 3 is an argv-only gate still
    # printing "arm symmetry holds" — the exact claim the row says section 10
    # cannot honestly make.
    parser.add_argument(
        "--with-surface",
        required=True,
        help="WITH-arm surface artifact (campaign_arm_surface.py --out)",
    )
    parser.add_argument(
        "--without-surface",
        required=True,
        help="WITHOUT-arm surface artifact (campaign_arm_surface.py --out)",
    )
    # The ONE thing the caller supplies about strength — and only because it
    # is the one fact the caller cannot be wrong about: WHERE it read the
    # file. Every judgement about what that file is WORTH is derived from
    # the surfaces themselves (N-6). 'local' is the default so that a
    # forgotten argument yields the WEAKEST claim, never the strongest.
    parser.add_argument(
        "--sibling-source",
        choices=list(SIBLING_SOURCES),
        default="local",
        help=(
            "where the caller READ the sibling surface: 'published' (from the shared "
            "campaign root) or 'local' (captured on this host during this run). This is "
            "a FACT about the read, not a claim about the evidence: whether a published "
            "file is genuinely cross-pod is derived from its own recorded host, revision "
            "and captured-at."
        ),
    )
    parser.add_argument(
        "--sibling-max-age-hours",
        type=int,
        default=DEFAULT_SIBLING_MAX_AGE_HOURS,
        help=(
            "beyond this age a cross-pod surface is reported 'cross_pod_stale' and loses "
            f"the verified label (default {DEFAULT_SIBLING_MAX_AGE_HOURS}). Staleness "
            "downgrades the claim; it is not itself a violation."
        ),
    )
    args = parser.parse_args()

    with open(args.with_output, encoding="utf-8") as fh:
        with_text = fh.read()
    with open(args.without_output, encoding="utf-8") as fh:
        without_text = fh.read()

    try:
        with_surface = _load_surface(args.with_surface)
        without_surface = _load_surface(args.without_surface)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[arm-symmetry] cannot read an arm surface: {exc}", file=sys.stderr)
        return 2

    try:
        scope = classify_comparison(
            with_surface,
            without_surface,
            now_epoch=time.time(),
            max_age_hours=args.sibling_max_age_hours,
        )
        argv_problems = check(
            with_text,
            without_text,
            workspace_root=args.workspace_root,
            band=args.band,
        )
        rows = spotlight_rows(with_text, without_text)
        by_layer = check_surfaces_by_layer(with_surface, without_surface, scope=scope)
        by_layer[LAYER_ARGV] = argv_problems + by_layer[LAYER_ARGV]
        rows_surface = surface_rows(with_surface, without_surface)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"[arm-symmetry] cannot parse a dry-run capture: {exc}", file=sys.stderr)
        return 2

    verdicts = layer_verdicts(by_layer, scope)
    problems = [problem for layer in LAYERS for problem in by_layer[layer]]

    print("[arm-symmetry] #255 population-knob spotlight (child argv):")
    for row in rows:
        print(row)
    print("[arm-symmetry] N-6 sibling-surface attribution:")
    for row in provenance_rows(scope, args.sibling_source):
        print(row)
    # The machine-readable handle the preflight reads back, so the R7 row can
    # state the SAME evidence state this checker derived rather than a second
    # opinion formed in bash.
    print(f"[arm-symmetry] evidence-state: {scope['evidence_state']}")
    print("[arm-symmetry] F-SCANG-4 surface layer:")
    for row in rows_surface:
        print(row)
    print("[arm-symmetry] layer verdicts (NOT COMPARED is a named absence, never a pass):")
    for verdict, layer, why in verdicts:
        print(f"  {verdict:13s} {layer} — {why}")
    if problems:
        print(f"[arm-symmetry] FAIL — {len(problems)} violation(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    compared = [layer for verdict, layer, _ in verdicts if verdict == "COMPARED"]
    not_compared = [layer for verdict, layer, _ in verdicts if verdict == "NOT COMPARED"]
    print(
        f"[arm-symmetry] PASS — no difference in {len(compared)} compared layer(s): "
        + "; ".join(compared)
    )
    if not_compared:
        print(
            f"[arm-symmetry] NOT PROVEN — {len(not_compared)} layer(s) were not compared "
            f"({'; '.join(not_compared)}). Their agreement is a construction artifact of a "
            f"{scope['evidence_state']} capture and is NOT evidence of arm symmetry."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
