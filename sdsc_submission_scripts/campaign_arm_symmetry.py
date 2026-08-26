#!/usr/bin/env python
"""Arm argv-symmetry check (#255 exposure determination — launch-blocking).

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
diff printed); exit 2 = a capture could not be parsed.
"""

from __future__ import annotations

import argparse
import json
import sys

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
    args = parser.parse_args()

    with open(args.with_output, encoding="utf-8") as fh:
        with_text = fh.read()
    with open(args.without_output, encoding="utf-8") as fh:
        without_text = fh.read()

    try:
        problems = check(
            with_text,
            without_text,
            workspace_root=args.workspace_root,
            band=args.band,
        )
        rows = spotlight_rows(with_text, without_text)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"[arm-symmetry] cannot parse a dry-run capture: {exc}", file=sys.stderr)
        return 2

    print("[arm-symmetry] #255 population-knob spotlight (child argv):")
    for row in rows:
        print(row)
    if problems:
        print(f"[arm-symmetry] FAIL — {len(problems)} violation(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("[arm-symmetry] PASS — arms differ only in declared arm policy + derived naming")
    return 0


if __name__ == "__main__":
    sys.exit(main())
