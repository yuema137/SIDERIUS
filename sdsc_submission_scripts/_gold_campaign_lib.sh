#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Gold campaign — SHARED LIBRARY (source, do not exec)
# ---------------------------------------------------------------------------
# Role   : the ONE shared boundary where the campaign's frozen authorities
#          are typed (D-ARCH-1, F-LAUNCH-1). Sourced by run_gold_campaign.sh
#          and by every stage script under it; NEVER by the X9 launchers.
#
# Owns   : the frozen-value table (the thirteen chain-boundary values from
#          docs/campaign/official_campaign_decisions.yaml — D-BUD-2 horizon,
#          D-BUD-6 epochs, D-BUD-7 trial portions, D-BUD-8 formal portions,
#          D-BUD-11/13 time budgets, P6-A skip delta, P6-B bypass delta),
#          the frozen LLM ROUTING authority (D-LLM-1, F-LLM-WIRE-1),
#          the OPERATOR-SUPPLIED required runtime-profile binding
#          (F-PROFILE-WIRE-1 — mechanism frozen here, value supplied at M4),
#          the band vocabulary + band->files + band->GPU maps
#          (EXCLUSIVE_SINGLE_BAND, operator hardware disposition 2026-08-26),
#          the campaign arm vocabulary (D-NAME-1: goldpod / blindpod;
#          R-ARM-STAMP-1: X9 labels refused by name), the retention guard
#          (R-RETENTION-1), the reserved-passthrough refusals, and the
#          bypass-ceiling emission probe (parallel-lane interface).
#
# Contract: docs/campaign/stage_artifact_contract.md (PR #329, FROZEN) —
#          workspace layout {root}/{arm}_band{BAND}, Stage-2 unit layout
#          {root}/stage2/{design}_{band}/ with COMPLETE.json, winner rule.
#
# Every function is side-effect free except for stderr diagnostics; sourcing
# this file performs no filesystem writes and launches nothing.
# ---------------------------------------------------------------------------

# Refuse direct execution: this file only defines values and functions.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "ERROR: _gold_campaign_lib.sh is a library — source it, do not execute it" >&2
    exit 1
fi

GOLD_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOLD_PROJECT_DIR="$(cd "${GOLD_LIB_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# THE FROZEN-VALUE TABLE — the thirteen typed chain-boundary values.
#
# ONE row per value; the argv builder DERIVES its tokens from these rows via
# gold_frozen_value, and the dry-run prints them verbatim, so deleting or
# renaming a row breaks BOTH surfaces and the failure NAMES the missing key
# (the mutation witness tests/unit/sdsc_submission_scripts/
# test_gold_campaign_entrypoint.py relies on).
#
# Key == the run_chain.sh flag name (parse_chain_args spelling), except
# `num_iterations`, which is the STAGE-1 SEARCH HORIZON (D-BUD-2: 20 is a
# maximum, not a target; a band may stop earlier only under the FCNet+2
# rule once A2-FCNET supplies a per-band reference).
#
# trial_max_epochs=2 / formal_max_epochs=1 — the D-BUD-6 frozen split,
# emitted since the chain grew the per-mode transport
# (run_one_iteration.py --trial_max_epochs / --formal_max_epochs; the tuner
# clamps at the plan boundary keyed on the round's is_trial authority).
# These are CEILINGS / workflow authorities — agents may NOT increase them;
# any legitimate training-validity mechanism may still terminate an invalid
# run earlier (decision D-BUD-6). The pair is emitted INSTEAD of the old
# mode-agnostic max_epochs=1 stand-in (the pre-split DECLARED LIMITATION):
# with both per-mode values typed, --max_epochs is fully shadowed at the
# clamp, and run_one_iteration.py's own default (--max_epochs 1) still
# rides along as the mode-agnostic fallback — the same value the retired
# row carried. --max_epochs stays RESERVED below so no passthrough can
# reintroduce a third epoch authority.
GOLD_FROZEN_ROWS=(
    "num_iterations=20"
    "trial_portion=0.1"
    "train_portion=0.1"
    "eval_portion=0.01"
    "formal_portion=1.0"
    "formal_train_portion=0.1"
    "formal_eval_portion=0.1"
    "trial_max_epochs=2"
    "formal_max_epochs=1"
    "trial_time_budget_minutes=30"
    "formal_time_budget_minutes=120"
    "skip_formal_min_delta=-2.0"
    "bypass_formal_time_budget_min_delta=0.5"
)

#: Stage-2 iteration count (D-ARCH-1/D-ARCH-2): a frozen-design retrain is
#: ONE iteration — the same pin the --fixed-candidate seam applies. The
#: 20-row above is the Stage-1 SEARCH horizon and must not leak into
#: Stage-2 argv.
GOLD_STAGE2_NUM_ITERATIONS=1

#: Bypass-ceiling interface (frozen contract; the IMPLEMENTATION lands in a
#: parallel lane). Emitted only when the chain actually parses the flag —
#: see gold_bypass_ceiling_args.
GOLD_BYPASS_FORMAL_TIME_BUDGET_MINUTES=200

#: THE FROZEN LLM ROUTING AUTHORITY (D-LLM-1; defect F-LLM-WIRE-1).
#:
#: The campaign pins every LLM role to the snapshot model in this file.
#: It is stated RELATIVE to the executing repository and resolved to an
#: ABSOLUTE path at bind time by gold_llm_config_args — run_chain.sh cd's
#: to the project dir before exec (lilab mode), so a relative path would
#: dangle (the same rule the advice artifact follows).
#:
#: WHY THIS IS A REFUSAL AND NOT A DEFAULT. `--llm_config` is optional all
#: the way down (_chain_common.sh LLM_CONFIG="" forwards nothing;
#: run_one_iteration.py falls back to WorkflowLLMConfig.uniform("gemini",
#: --llm_model) whose default is "gemini-3.1-pro-preview"). So a campaign
#: launch that simply OMITS the flag still exits 0 and still produces
#: records — it just runs the entire official campaign on a different model
#: than the frozen one, with nothing on any surface saying so. That is the
#: declared-but-unconsumed class: the pin was real, the file was correct,
#: and nothing on the campaign path consumed it. Emission is therefore
#: MANDATORY on the campaign path and an unresolvable value REFUSES by
#: name, rather than self-disabling the way the bypass ceiling above does
#: (that flag may legitimately not be parseable yet; this one always is).
GOLD_LLM_CONFIG_RELPATH="llm_configs/openai_tiered_pro.json"

#: FCNet+2 band-local early-stop margin (golden notebook / D-BUD-17). The
#: rule is only EVALUABLE once A2-FCNET produces per-band FCNet references;
#: until then a band runs its full horizon (the notebook's recorded interim).
GOLD_FCNET_STOP_MARGIN=2.0

#: The four campaign bands (contract vocabulary; same literals as the X9
#: band launcher's authority map — drift is caught by the pinned test).
GOLD_BANDS=("0-3" "4-9" "10-14" "15-19")

#: The campaign arm vocabulary (D-NAME-1, FROZEN).
GOLD_ARMS=("goldpod" "blindpod")

# gold_frozen_value KEY — echo the frozen value for KEY, or fail NAMING the
# missing key. The single lookup path both the argv builder and any stage
# consult; a dropped table row surfaces here, by name.
gold_frozen_value() {
    local key="$1" row
    for row in "${GOLD_FROZEN_ROWS[@]}"; do
        if [ "${row%%=*}" = "$key" ]; then
            printf '%s\n' "${row#*=}"
            return 0
        fi
    done
    echo "ERROR: FROZEN TABLE MISSING VALUE: '$key' has no row in GOLD_FROZEN_ROWS (_gold_campaign_lib.sh)" >&2
    return 1
}

# gold_print_frozen_table — the dry-run's effective-value block, printed
# verbatim from the table (one `key=value` line each, prefixed).
gold_print_frozen_table() {
    local row
    echo "[gold-campaign] FROZEN VALUES (typed at the shared boundary; decisions D-BUD-2/6/7/8, D-BUD-11/13, P6-A, P6-B):"
    for row in "${GOLD_FROZEN_ROWS[@]}"; do
        echo "[gold-campaign]   frozen ${row}"
    done
    echo "[gold-campaign]   frozen stage2_num_iterations=${GOLD_STAGE2_NUM_ITERATIONS} (D-ARCH-2 fixed-candidate pin)"
    echo "[gold-campaign]   frozen fcnet_stop_margin=${GOLD_FCNET_STOP_MARGIN} (evaluable only with a per-band reference; A2-FCNET)"
    echo "[gold-campaign]   frozen llm_config=${GOLD_LLM_CONFIG_RELPATH} (D-LLM-1; resolved absolute at bind, REFUSES if absent)"
    # F-GATE-WIRE-1 (#316 B1): printed so the two delta rows above can be
    # read as ARMED rather than merely declared. Without the switch they are
    # transported, parsed and then never consumed, and no surface says so.
    echo "[gold-campaign]   frozen enable_chain_incumbent_formal_gates=on (F-GATE-WIRE-1; ARMS skip_formal_min_delta + bypass_formal_time_budget_min_delta — without it both gates resolve gates_disabled)"
    # F-PROFILE-WIRE-1: ALWAYS printed, declared or not — an undeclared
    # runtime-profile binding is a launch decision an operator must be able
    # to SEE, not an absent line they have to know to look for.
    if [ -n "${GOLD_REQUIRED_RUNTIME_PROFILE:-}" ]; then
        echo "[gold-campaign]   supplied required_runtime_profile=${GOLD_REQUIRED_RUNTIME_PROFILE} sha256=${GOLD_REQUIRED_RUNTIME_PROFILE_SHA256:-(unset)} artifact=${GOLD_REQUIRED_RUNTIME_PROFILE_PATH:-(unset)} (F-PROFILE-WIRE-1; fail-closed, declared artifact only, no discovery)"
    else
        echo "[gold-campaign]   supplied required_runtime_profile=(none — legacy ladder: measured > shipped > uncalibrated; declare at M4 with --gold_required_runtime_profile[_sha256])"
    fi
    # D-HW-6: ALWAYS printed, supplied or not. An UNCAPPED campaign on four
    # co-resident bands is a launch fact an operator must be able to SEE; an
    # absent line is indistinguishable from a seam that was never wired,
    # which is exactly how this defect family stayed invisible.
    if [ -n "${GOLD_TRIAL_VRAM_BUDGET_GB:-}" ]; then
        echo "[gold-campaign]   supplied vram_budget=trial:${GOLD_TRIAL_VRAM_BUDGET_GB} formal:${GOLD_FORMAL_VRAM_BUDGET_GB:-(unset)} (D-HW-6; carried VERBATIM to --trial/--formal_vram_budget_gb — units NOT interpreted here)"
    else
        echo "[gold-campaign]   supplied vram_budget=(none — no operator ceiling; D-HW-6 is HARDWARE_DERIVED / PENDING_H100_QUALIFICATION, so the chain's free-VRAM default governs both modes)"
    fi
    # F-GENLIB-WIRE-1: the launch REFUSES when this is unset, so by the time
    # the table prints it is always a declared value. Printed so the operator
    # can confirm WHICH root this campaign's promoted capabilities land in —
    # the properties of that root are checked by campaign_preflight R1c.
    echo "[gold-campaign]   supplied generated_library=${GOLD_GENERATED_LIBRARY_DIR:-(unset — launch refused)} (F-GENLIB-WIRE-1; \$SIDERIUS_GENERATED_LIBRARY_DIR, validated by preflight R1c)"
}

# gold_bypass_ceiling_args — sets GOLD_BYPASS_CEILING_ARGS.
#
# The 200-minute bypass ceiling is part of the frozen contract
# (decisions: bypass_qualified_formal_attempt 200 / 200), but the flag that
# carries it (--bypass_formal_time_budget_minutes) is implemented in a
# PARALLEL lane and has not landed at this branch's base. Emitting an
# unknown flag would refuse every launch, so emission is gated on a
# build-time probe of the two surfaces that must both accept it: the chain
# parser (_chain_common.sh) and the iteration runner's argparse
# (run_one_iteration.py). When the parallel PR lands with this spelling the
# emission enables itself; the integration witness runs then.
gold_bypass_ceiling_args() {
    GOLD_BYPASS_CEILING_ARGS=()
    if grep -q -- "--bypass_formal_time_budget_minutes)" "${GOLD_LIB_DIR}/_chain_common.sh" \
        && grep -q -- '"--bypass_formal_time_budget_minutes"' "${GOLD_LIB_DIR}/run_one_iteration.py"; then
        GOLD_BYPASS_CEILING_ARGS=(--bypass_formal_time_budget_minutes "$GOLD_BYPASS_FORMAL_TIME_BUDGET_MINUTES")
    else
        echo "[gold-campaign] NOTE: --bypass_formal_time_budget_minutes ${GOLD_BYPASS_FORMAL_TIME_BUDGET_MINUTES} NOT emitted:" >&2
        echo "  the transport is only half on disk (_chain_common.sh parses the flag at this tip; the run_one_iteration.py argparse half lands with #334);" >&2
        echo "  emission self-enables when both _chain_common.sh and run_one_iteration.py accept it." >&2
    fi
}

# gold_llm_config_args — sets GOLD_LLM_CONFIG_ARGS (plus the resolved
# GOLD_LLM_CONFIG_ABS / GOLD_LLM_CONFIG_SHA256 the launch manifest records),
# or REFUSES naming the flag.
#
# The anti-silence witness: omitting --llm_config is INDISTINGUISHABLE from
# passing it, at every surface an operator looks at, until the run is over.
# So the campaign path refuses instead of proceeding, and the refusal names
# --llm_config, the file it expected, and what the omission would have done.
gold_llm_config_args() {
    local abs="${GOLD_PROJECT_DIR}/${GOLD_LLM_CONFIG_RELPATH}"
    if [ ! -f "$abs" ] || [ ! -r "$abs" ]; then
        echo "ERROR: the campaign's frozen LLM routing config is unavailable, so --llm_config" >&2
        echo "  cannot be bound and this launch is REFUSED (F-LLM-WIRE-1):" >&2
        echo "    expected: $abs" >&2
        echo "    declared: GOLD_LLM_CONFIG_RELPATH=${GOLD_LLM_CONFIG_RELPATH} (_gold_campaign_lib.sh)" >&2
        echo "  Launching without --llm_config does NOT fail — it silently resolves every LLM" >&2
        echo "  role to run_one_iteration.py's deprecated all-Gemini default" >&2
        echo "  (gemini-3.1-pro-preview) instead of the campaign's pinned snapshot model," >&2
        echo "  and the run still exits 0. Restore the file or fix the declared path." >&2
        return 1
    fi
    GOLD_LLM_CONFIG_ABS="$abs"
    GOLD_LLM_CONFIG_SHA256="$(sha256sum "$abs" | awk '{print $1}')"
    GOLD_LLM_CONFIG_ARGS=(--llm_config "$abs")
}

# gold_required_profile_args — sets GOLD_REQUIRED_PROFILE_ARGS from the
# OPERATOR-SUPPLIED runtime-profile declaration (F-PROFILE-WIRE-1).
#
# WHY THIS VALUE IS SUPPLIED AND NOT FROZEN, unlike every other authority in
# this file. A required binding is the pair (profile key, sha256 of the
# MEASURED overlay). That overlay is produced by GoldPod qualification (M4)
# — it is post-tag measurement data, so its digest cannot exist in tagged
# code. Freezing an empty constant here and filling it on the pod would make
# M4 require an edit to TAGGED code, which is precisely the outcome the
# operator's ruling says must fail M4 rather than be papered over. So the
# campaign freezes the MECHANISM and its OBSERVABILITY; qualification
# supplies the VALUE, through --gold_required_runtime_profile[_sha256] on
# the entrypoint, threaded down exactly like --gold_advice_file.
#
# Absent == undeclared == the legacy ladder (measured > shipped >
# uncalibrated), and NO token reaches the child argv — so a pre-M4 campaign
# launch is byte-identical to today. Absence is nonetheless PRINTED by
# gold_print_frozen_table and RECORDED in the launch manifest, so
# "no binding was declared" is an observed fact rather than a silence.
#
# A HALF declaration refuses here, at the boundary, rather than in the child:
# the stage scripts fork one background chain per band, so a digest typo
# discovered downstream would already have launched the fleet.
gold_required_profile_args() {
    local path="${GOLD_REQUIRED_RUNTIME_PROFILE_PATH:-}"
    local key="${GOLD_REQUIRED_RUNTIME_PROFILE:-}"
    local sha="${GOLD_REQUIRED_RUNTIME_PROFILE_SHA256:-}"
    GOLD_REQUIRED_PROFILE_ARGS=()
    if [ -z "$path" ] && [ -z "$key" ] && [ -z "$sha" ]; then
        return 0
    fi
    if [ -z "$path" ] || [ -z "$key" ] || [ -z "$sha" ]; then
        echo "ERROR: an INCOMPLETE required runtime-profile declaration was supplied, so" >&2
        echo "  this launch is REFUSED (F-PROFILE-WIRE-1):" >&2
        echo "    --gold_required_runtime_profile_path   = ${path:-(unset)}" >&2
        echo "    --gold_required_runtime_profile        = ${key:-(unset)}" >&2
        echo "    --gold_required_runtime_profile_sha256 = ${sha:-(unset)}" >&2
        echo "  The binding is the TRIPLE (artifact path, profile key, certified sha256);" >&2
        echo "  part of it is not a weaker requirement, it is NO requirement — the chain" >&2
        echo "  would fall back to the measured>shipped>uncalibrated ladder while the" >&2
        echo "  operator believed a profile was pinned. Supply all three or none." >&2
        return 1
    fi
    if [[ "$path" != /* ]]; then
        echo "ERROR: --gold_required_runtime_profile_path '${path}' is not ABSOLUTE" >&2
        echo "  (F-PROFILE-WIRE-1). run_chain.sh cd's to the project dir before exec, so" >&2
        echo "  a relative artifact path would name a different file than the one" >&2
        echo "  qualified — or none at all." >&2
        return 1
    fi
    if [[ "$key" != */* ]]; then
        echo "ERROR: --gold_required_runtime_profile '${key}' is not '<gpu_slug>/<regime>'" >&2
        echo "  (F-PROFILE-WIRE-1). Copy the key from the qualification run's recorded" >&2
        echo "  provenance, e.g. nvidia_h100_80gb_hbm3/single." >&2
        return 1
    fi
    if [[ ! "$sha" =~ ^[0-9a-f]{64}$ ]]; then
        echo "ERROR: --gold_required_runtime_profile_sha256 '${sha}' is not 64 lowercase" >&2
        echo "  hex characters (F-PROFILE-WIRE-1). Take it from the measured overlay:" >&2
        echo "    sha256sum \"\${SIDERIUS_CALIBRATION_DIR:-\$HOME/.siderius}/runtime_profiles_<slug>.json\"" >&2
        return 1
    fi
    GOLD_REQUIRED_PROFILE_ARGS=(
        --required_runtime_profile_path "$path"
        --required_runtime_profile "$key"
        --required_runtime_profile_sha256 "$sha"
    )
}

# gold_vram_budget_args — sets GOLD_VRAM_BUDGET_ARGS from the
# OPERATOR-SUPPLIED per-mode VRAM ceiling (D-HW-6).
#
# THIS FUNCTION CARRIES A VALUE AND NEVER SUPPLIES ONE. The campaign's
# ceiling is HARDWARE_DERIVED / PENDING_H100_QUALIFICATION — deliberately
# superseded from a frozen number so that no ceiling can acquire authority
# in tagged code before it has been measured. So unlike every frozen row
# above, there is no GOLD_*_VRAM_BUDGET constant here, and there must never
# be one: a default would be indistinguishable from a measurement at every
# surface an operator reads.
#
# WHY THE SEAM IS NEEDED AT ALL. The chain below has carried a complete
# transport all along (_chain_common.sh parses --trial_vram_budget_gb /
# --formal_vram_budget_gb and forwards each into APP_ARGS;
# run_one_iteration.py binds them onto WorkflowLaunchConfig). The GOLD layer
# had nothing: no flag, no forwarding, no reserved entry. A qualified number
# therefore had no path onto the campaign argv, and the only way to apply
# one would have been to edit tagged code on the pod — the outcome that must
# FAIL qualification rather than be papered over.
#
# BOTH OR NEITHER. These are two INDEPENDENT per-mode ceilings, so they are
# not collapsed into a single operator value: that would assert
# trial == formal, which nobody decided, and qualification may measure them
# differently (formal rounds are the larger). But a HALF supply is refused
# here, at the boundary, for the same reason the profile triple is: the
# stage scripts fork one background chain per band, so a half cap noticed
# downstream has already launched the fleet — and a capped trial beside an
# uncapped formal on four co-resident bands is precisely the exhaustion the
# ceiling exists to prevent, while LOOKING like a configuration.
#
# ABSENT == UNSUPPLIED == no operator ceiling, and NO token reaches the
# child argv, so a pre-qualification launch is byte-identical to a pre-seam
# one. This is deliberately NOT a refusal, unlike the generated-library
# root: omitting a ceiling diverges from no pinned authority (_chain_common
# defaults both budgets to "" == omit — the state every campaign launch has
# run in), so refusing would make the seam a launch blocker for a value the
# campaign has deliberately not frozen. The absence is instead PRINTED by
# gold_print_frozen_table and RECORDED in the launch manifest, so "no
# ceiling was supplied" is an observed fact rather than a silence.
#
# UNITS ARE NOT SETTLED HERE, AND MUST NOT BE. D-HW-6 flags a live GB/GiB
# gap: these flags spell '_gb', but agent/skills/evaluate_vram_skill/
# wrapper.py computes min(physical_cap, budget * _GB) with _GB = 1024**3,
# i.e. GiB. The value therefore crosses UNCHANGED — no conversion, no
# normalisation, no unit-assuming validator — because a transport that
# silently interprets units acquires an authority nobody granted and would
# close D-HW-6's question by accident. The one check below is unit-NEUTRAL:
# a strictly positive decimal is positive whether it is read as GB or GiB.
#
# PER-BAND CALL, NON-DIVERGENT BY CONSTRUCTION. Like every builder here this
# runs once per forked band, not once per launch. That is safe ONLY because
# the value is argv-transported: stage1_search.sh builds BAND_ARGS_COMMON
# once and expands the identical array into every fork, and each band resets
# the variables before parsing, so nothing ambient or on-disk can differ
# between fork 1 and fork 4. A value DERIVED per band (a file digest, a
# timestamp) would not have that property.
gold_vram_budget_args() {
    local trial="${GOLD_TRIAL_VRAM_BUDGET_GB:-}"
    local formal="${GOLD_FORMAL_VRAM_BUDGET_GB:-}"
    local label value
    GOLD_VRAM_BUDGET_ARGS=()
    if [ -z "$trial" ] && [ -z "$formal" ]; then
        return 0
    fi
    if [ -z "$trial" ] || [ -z "$formal" ]; then
        echo "ERROR: an INCOMPLETE VRAM ceiling was supplied, so this launch is" >&2
        echo "  REFUSED (D-HW-6):" >&2
        echo "    --gold_trial_vram_budget_gb  = ${trial:-(unset)}" >&2
        echo "    --gold_formal_vram_budget_gb = ${formal:-(unset)}" >&2
        echo "  Capping one mode and not the other is not a weaker ceiling, it is a" >&2
        echo "  ceiling on the wrong half: the unbounded mode still runs unbounded," >&2
        echo "  on the same card, beside three co-resident bands. Supply both or none." >&2
        return 1
    fi
    for label in trial formal; do
        if [ "$label" = trial ]; then value="$trial"; else value="$formal"; fi
        # Unit-NEUTRAL shape check. Refused here rather than by the child's
        # argparse, which would raise only after the fleet is already up.
        # '0' is rejected on purpose: it is not "disabled" but a ZERO-BYTE
        # cap (min(physical_cap, 0)) in which nothing fits, so an operator
        # typing it to mean "no ceiling" would get "refuse everything".
        if ! [[ "$value" =~ ^[0-9]+(\.[0-9]+)?$ ]] || [[ "$value" =~ ^0+(\.0+)?$ ]]; then
            echo "ERROR: --gold_${label}_vram_budget_gb '${value}' is not a positive number" >&2
            echo "  (D-HW-6). Supply a bare decimal — no unit suffix, no exponent: the" >&2
            echo "  value is carried VERBATIM to the chain's --${label}_vram_budget_gb," >&2
            echo "  and this launcher deliberately does not interpret its units (the" >&2
            echo "  GB/GiB question is open at the decision record and must be settled" >&2
            echo "  there, not by a transport quietly converting on the way past)." >&2
            return 1
        fi
    done
    GOLD_VRAM_BUDGET_ARGS=(
        --trial_vram_budget_gb "$trial"
        --formal_vram_budget_gb "$formal"
    )
}

# gold_require_generated_library — REFUSE a campaign launch that has not
# DECLARED where promoted capabilities live (F-GENLIB-WIRE-1).
#
# This asserts that the DECISION was made; it does not dictate the value, and
# nothing machine-specific enters tracked code. The operator exports
# SIDERIUS_GENERATED_LIBRARY_DIR (the SIDERIUS_CALIBRATION_DIR shape), the
# campaign_preflight R1c row validates the resolved root's PROPERTIES through
# the production authority, and this function puts the requirement ON the
# launch path by construction — which a preflight-only guard cannot do,
# because preflight is a separate invocation an operator can skip.
#
# The anti-silence witness, same as --llm_config: leaving it unset does NOT
# fail. The library silently resolves to the DEFAULT
# ~/.siderius/generated_library, which on a pod is the ephemeral container
# overlay AND is shared across campaigns — so a previous run's promoted
# models and losses appear in this run's proposer surface, the arms stop
# being isolated, and the run still exits 0. Refusing here is the point:
# every launch this rejects is one that would have accumulated into a root
# nobody declared.
#
# Note this necessarily tests that the variable was EXPORTED, not merely
# assigned: the entrypoint is exec'd, so a plain shell assignment never
# reaches it — and would equally never reach the chain's Python children.
gold_require_generated_library() {
    local raw="${SIDERIUS_GENERATED_LIBRARY_DIR:-}"
    # Mirror the authority's `.strip()`: whitespace is not a declaration.
    raw="$(printf '%s' "$raw" | tr -d '[:space:]')"
    if [ -z "$raw" ]; then
        echo "ERROR: SIDERIUS_GENERATED_LIBRARY_DIR is not exported, so this campaign" >&2
        echo "  launch is REFUSED (F-GENLIB-WIRE-1)." >&2
        echo "  It must name an ABSOLUTE, PERSISTENT, CAMPAIGN-OWNED and FRESH directory" >&2
        echo "  for promoted models, losses and the capability index. This launcher does" >&2
        echo "  not choose it for you: the correct path is a property of the machine and" >&2
        echo "  of which campaign this is, so it must be a recorded operator decision." >&2
        echo "  Leaving it unset does NOT fail — the library resolves to the DEFAULT" >&2
        echo "  ~/.siderius/generated_library, which on a pod is the ephemeral container" >&2
        echo "  overlay AND is shared across campaigns, so an earlier run's promoted" >&2
        echo "  capabilities enter this run's proposer surface and the run still exits 0." >&2
        echo "  Export it (a plain shell assignment is not enough — the chain's children" >&2
        echo "  read the ENVIRONMENT), then re-run campaign_preflight.sh: its R1c row" >&2
        echo "  validates the resolved root through core.generated_library itself." >&2
        return 1
    fi
    GOLD_GENERATED_LIBRARY_DIR="${SIDERIUS_GENERATED_LIBRARY_DIR}"
}

# gold_frozen_chain_args STAGE — sets GOLD_FROZEN_CHAIN_ARGS: the typed
# run_chain.sh tokens for every frozen value, plus retention.
#
#   STAGE = stage1 : --num_iterations <horizon 20>
#   STAGE = stage2 : --num_iterations 1 (D-ARCH-2 retrain pin); the horizon
#                    row is still consulted so a dropped row fails stage-2
#                    builds too.
#
# R-RETENTION-1: the LAST token is always --no-cleanup_denoised — official
# FORMAL execution RETAINS deliverables (contract retention clause), so the
# child argv carries NO --cleanup_denoised and run_comparison's default
# (False) governs. The historical standard command's --cleanup_denoised is
# exactly the defect this closes.
gold_frozen_chain_args() {
    local stage="$1" key v horizon
    GOLD_FROZEN_CHAIN_ARGS=()
    horizon="$(gold_frozen_value num_iterations)" || return 1
    case "$stage" in
        stage1) GOLD_FROZEN_CHAIN_ARGS+=(--num_iterations "$horizon") ;;
        stage2) GOLD_FROZEN_CHAIN_ARGS+=(--num_iterations "$GOLD_STAGE2_NUM_ITERATIONS") ;;
        *)
            echo "ERROR: gold_frozen_chain_args: unknown stage '$stage' (stage1|stage2)" >&2
            return 1 ;;
    esac
    for key in trial_portion train_portion eval_portion \
        formal_portion formal_train_portion formal_eval_portion \
        trial_max_epochs formal_max_epochs \
        trial_time_budget_minutes formal_time_budget_minutes \
        skip_formal_min_delta bypass_formal_time_budget_min_delta; do
        v="$(gold_frozen_value "$key")" || return 1
        GOLD_FROZEN_CHAIN_ARGS+=("--${key}" "$v")
    done
    # F-GATE-WIRE-1 (#316 B1) — THE SWITCH THAT MAKES THE TWO DELTAS ABOVE
    # MEAN ANYTHING. Emitted UNCONDITIONALLY, immediately after them, in the
    # ONE builder both stages consume, so a stage-2 unit can never run under
    # different formal-gate semantics than the stage-1 band it retrains.
    #
    # WHY THIS IS NOT A FROZEN TABLE ROW. GOLD_FROZEN_ROWS is a key=value
    # table and its consumer loop emits `--${key} "$v"`; this is an argparse
    # store_true switch that takes NO value. A table row would emit
    # `--enable_chain_incumbent_formal_gates 1`, and _chain_common.sh:370
    # `shift`s once — the stray `1` would fall through as an unknown token.
    # The table's canonical row count is also a pinned frozen declaration.
    #
    # WHY THERE IS NO CAPABILITY PROBE, unlike gold_bypass_ceiling_args.
    # Both transport halves are on disk at this tip (_chain_common.sh:370
    # parses, :663 forwards; run_one_iteration.py:1047 argparse), so there is
    # nothing to probe. A probe would also be the WRONG pattern here: the
    # bypass-ceiling probe SELF-DISABLES when the flag is unparseable, and
    # silent self-disablement is precisely the defect class this closes.
    #
    # WHAT THE OMISSION DID. --skip_formal_min_delta -2.0 and
    # --bypass_formal_time_budget_min_delta 0.5 were transported and PARSED
    # all the way down, and then never consumed:
    # ml_hyperparameter_tune_agent.py:1103-1107 nulls the reference when the
    # switch is off (`_consumed_reference = ... if
    # enable_chain_incumbent_formal_gates else None`), so
    # policy._resolve_formal_comparison_thresholds returns
    # (None, None, None, "gates_disabled") and BOTH gates go inert —
    # _should_skip_formal returns False at policy.py:269-270, and
    # _should_bypass_formal_time_budget (which is NOT itself gates-aware)
    # returns False on its `threshold is None` guard. The launch still
    # exits 0 and every surface still shows the frozen deltas. Restoring the
    # switch re-arms BOTH gates at once — they are one fix, not two.
    # Provenance: the predecessor campaign emitted this on the line directly
    # above the same two deltas (launch_v20_campaign.sh:158-160); Gold copied
    # the deltas and dropped the switch.
    GOLD_FROZEN_CHAIN_ARGS+=(--enable_chain_incumbent_formal_gates)
    gold_bypass_ceiling_args
    GOLD_FROZEN_CHAIN_ARGS+=(${GOLD_BYPASS_CEILING_ARGS[@]+"${GOLD_BYPASS_CEILING_ARGS[@]}"})
    # D-LLM-1: bound HERE, in the ONE builder both stages consume, so a
    # stage-2 unit can never run on a different model than a stage-1 band.
    gold_llm_config_args || return 1
    GOLD_FROZEN_CHAIN_ARGS+=("${GOLD_LLM_CONFIG_ARGS[@]}")
    # F-PROFILE-WIRE-1: bound HERE, in the ONE builder both stages consume,
    # so a stage-2 unit can never resolve a different runtime profile than
    # the stage-1 band it retrains. Empty when undeclared — the guarded
    # expansion keeps the undeclared child argv byte-identical.
    gold_required_profile_args || return 1
    GOLD_FROZEN_CHAIN_ARGS+=(${GOLD_REQUIRED_PROFILE_ARGS[@]+"${GOLD_REQUIRED_PROFILE_ARGS[@]}"})
    # D-HW-6: bound HERE, in the ONE builder both stages consume, so a
    # stage-2 retrain can never run under a different memory regime than the
    # stage-1 band whose design it retrains. Empty when unsupplied — the
    # guarded expansion keeps the unsupplied child argv byte-identical.
    gold_vram_budget_args || return 1
    GOLD_FROZEN_CHAIN_ARGS+=(${GOLD_VRAM_BUDGET_ARGS[@]+"${GOLD_VRAM_BUDGET_ARGS[@]}"})
    GOLD_FROZEN_CHAIN_ARGS+=(--no-cleanup_denoised)
}

# gold_band_files BAND — echo the DS8 health-file list for BAND, or refuse.
# Same literals as launch_prior_baseline_experiment.sh's authority table
# (that launcher stays the X9 authority; the pinned unit test cross-checks
# the two tables so they cannot drift apart silently).
gold_band_files() {
    case "$1" in
        0-3)   echo "0,1,2,3" ;;
        4-9)   echo "4,5,6,7,8,9" ;;
        10-14) echo "10,11,12,13,14" ;;
        15-19) echo "15,16,17,18,19" ;;
        *)
            echo "ERROR: unknown band '$1' (expected 0-3, 4-9, 10-14 or 15-19)" >&2
            return 1 ;;
    esac
}

# gold_band_gpu BAND — echo the CUDA_VISIBLE_DEVICES index for BAND
# (frozen formal hardware disposition, operator 2026-08-26: 4 x H100_SXM,
# EXCLUSIVE_SINGLE_BAND residency, GPU 0/1/2/3 -> bands 0-3/4-9/10-14/15-19).
gold_band_gpu() {
    case "$1" in
        0-3)   echo 0 ;;
        4-9)   echo 1 ;;
        10-14) echo 2 ;;
        15-19) echo 3 ;;
        *)
            echo "ERROR: unknown band '$1' (expected 0-3, 4-9, 10-14 or 15-19)" >&2
            return 1 ;;
    esac
}

# gold_band_args BAND — sets GOLD_BAND_ARGS: the DS8-mandatory pair.
gold_band_args() {
    local band="$1" files
    files="$(gold_band_files "$band")" || return 1
    GOLD_BAND_ARGS=(--data_scope "$band" --health_gate_files "$files")
}

# gold_select_bands ONLY_CSV — echo the selected bands, one per line, in
# CANONICAL order (same selection semantics as _chain_common's
# filter_roster: empty CSV = all; unknown / duplicate / blank selection
# refuses, never falls back to all).
gold_select_bands() {
    local only_csv="$1"
    if [ -z "$only_csv" ]; then
        printf '%s\n' "${GOLD_BANDS[@]}"
        return 0
    fi
    local requested=() raw name seen known band
    IFS=',' read -ra _parts <<< "$only_csv"
    for raw in "${_parts[@]}"; do
        name="$(echo "$raw" | xargs)"
        [ -z "$name" ] && continue
        for seen in ${requested[@]+"${requested[@]}"}; do
            if [ "$seen" = "$name" ]; then
                echo "[gold-campaign] duplicate band in --only: '$name'" >&2
                return 1
            fi
        done
        known=0
        for band in "${GOLD_BANDS[@]}"; do
            [ "$band" = "$name" ] && known=1
        done
        if [ "$known" = 0 ]; then
            echo "[gold-campaign] unknown band in --only: '$name' (valid: ${GOLD_BANDS[*]})" >&2
            return 1
        fi
        requested+=("$name")
    done
    if [ "${#requested[@]}" -eq 0 ]; then
        echo "[gold-campaign] --only selected nothing (valid: ${GOLD_BANDS[*]})" >&2
        return 1
    fi
    for band in "${GOLD_BANDS[@]}"; do
        for name in "${requested[@]}"; do
            [ "$name" = "$band" ] && printf '%s\n' "$band"
        done
    done
    # EXPLICIT, and load-bearing. Falling off the end returns the status of
    # the last command run, which here is the emission loop's final
    # `[ "$name" = "$band" ] && printf` — and that test FAILS whenever the
    # last band in GOLD_BANDS was not selected. So `--only 0-3` returned 1
    # while having printed the correct selection, and the caller's
    # `SELECTED="$(gold_select_bands "$ONLY")" || return 1` turned that into
    # a launch refusal with NO message on any stream. Every refusal above
    # returns 1 by name; success must say 0 by name too.
    return 0
}

# gold_arm_args ARM ADVICE_FILE — sets GOLD_ARM_ARGS.
#
#   goldpod  : --experiment_arm goldpod --no-ml_lit_review_enabled
#              --advice <abs advice file>          (T-IMPL-1 / D-TREAT-1)
#   blindpod : --experiment_arm blindpod --no-ml_lit_review_enabled
#              and REFUSES an advice file (WITHOUT_ADVICE arm; the absence
#              is recorded in the launch manifest as advice=EXPLICIT_NONE —
#              no positive no-advice argv token exists today).
#
# The arm label is CAMPAIGN vocabulary only (R-ARM-STAMP-1): the X9 labels
# are refused BY NAME because experiment_arm enters RunInvariants._CANONICAL
# and a wrong label is pinned and compared, not merely recorded.
#
# Literature review: operator ruling Q-LIT-1 = OFF, symmetric across arms
# (Q-LIT-1-CONSTRAINT). The EXPLICIT negative flag is forwarded (arXiv U3)
# so the OFF arm is recorded positively on the child argv — a NAMED absence,
# never a YAML-default inheritance.
gold_arm_args() {
    local arm="$1" advice="$2" expected_sha="${3:-}" advice_abs observed_sha
    case "$arm" in
        with-prior-art|without-prior-art)
            echo "ERROR: --arm '$arm' is the X9 experiment's label and is refused for the" >&2
            echo "  campaign (R-ARM-STAMP-1: experiment_arm is pinned by RunInvariants._CANONICAL;" >&2
            echo "  a wrong label fails closed on resume while looking authoritative)." >&2
            echo "  Campaign arms: ${GOLD_ARMS[*]}" >&2
            return 1 ;;
        goldpod)
            if [ -z "$advice" ]; then
                echo "ERROR: --arm goldpod requires --gold_advice_file PATH (the treatment" >&2
                echo "  boundary, D-TREAT-1/T-IMPL-1: the WITH_ADVICE arm receives the immutable" >&2
                echo "  advice artifact at every proposer round; content is owned by the gold" >&2
                echo "  advice lane and arrives as this file)." >&2
                return 1
            fi
            if [ ! -f "$advice" ]; then
                echo "ERROR: --gold_advice_file not found: $advice" >&2
                return 1
            fi
            # run_chain.sh cd's to the project dir before exec (lilab mode),
            # so a relative path would dangle — same rule as the
            # fixed-candidate seam's abs-path conversion.
            advice_abs="$(cd "$(dirname "$advice")" && pwd)/$(basename "$advice")"
            # OBSERVE the treatment identity here, off the path just resolved,
            # so the bytes hashed are the bytes the child is told to read.
            # `awk '{print $1}'` strips the FILE NAME `sha256sum` prints after
            # the digest; without it the run's scientific identity would encode
            # this machine's directory layout (run_one_iteration.py refuses
            # such a value, but the refusal belongs here, at the boundary).
            observed_sha="$(sha256sum "$advice_abs" | awk '{print $1}')"
            if [ -z "$observed_sha" ]; then
                echo "ERROR: could not hash the advice artifact at $advice_abs; the campaign's" >&2
                echo "  treatment identity cannot be bound and this launch is REFUSED." >&2
                return 1
            fi
            # THE CHECK THAT MAKES FOUR BANDS ONE TREATMENT.
            #
            # stage1_search.sh staggers four forks and each forked
            # stage1_run_band.sh calls THIS function itself, so without an
            # inherited value each band would hash the artifact at its own
            # launch time, declare its own digest, and have its child certify
            # against it -- trivially equal, always. Four bands would run into
            # four SEPARATE workspaces that no per-workspace lock can ever
            # compare, and an edit made during the stagger window would go
            # undetected with every check reporting green.
            #
            # The campaign entrypoint computes the digest ONCE and threads it
            # down (--gold_advice_sha256), exactly as F-PROFILE-WIRE-1 threads
            # its declaration triple. Comparing this band's own observation
            # against that single value is what converts a tautology into a
            # check. Empty == no campaign-level declaration (a directly-invoked
            # band, or a hand run): the observation still binds, there is just
            # nothing to inherit.
            if [ -n "$expected_sha" ] && [ "$expected_sha" != "$observed_sha" ]; then
                echo "ERROR: the advice artifact is NOT the one this campaign bound, so this" >&2
                echo "  band is REFUSED before it launches:" >&2
                echo "    artifact : $advice_abs" >&2
                echo "    campaign : $expected_sha  (computed once by run_gold_campaign.sh)" >&2
                echo "    observed : $observed_sha  (this band, now)" >&2
                echo "  The bands are staggered and write to SEPARATE workspaces, so two" >&2
                echo "  different treatments would never meet in one invariants lock and" >&2
                echo "  nothing downstream could tell the arms apart. Restore the artifact" >&2
                echo "  or relaunch the campaign against the file you mean to test." >&2
                return 1
            fi
            GOLD_ADVICE_ABS="$advice_abs"
            GOLD_ADVICE_SHA256="$observed_sha"
            # The OBSERVED digest is declared to the child, which certifies it
            # against its OWN read and pins that observation. When a campaign
            # value was inherited the refusal above proves the two are equal,
            # so this is the campaign's identity; when none was, it is the only
            # honest value there is.
            GOLD_ARM_ARGS=(--experiment_arm goldpod --no-ml_lit_review_enabled \
                --advice "$advice_abs" --advice_sha256 "$observed_sha")
            ;;
        blindpod)
            if [ -n "$advice" ]; then
                echo "ERROR: --arm blindpod refuses --gold_advice_file: blindpod is the" >&2
                echo "  WITHOUT_ADVICE arm (D-NAME-1); its treatment is the EXPLICIT absence" >&2
                echo "  of the artifact (plan section 5.6)." >&2
                return 1
            fi
            if [ -n "$expected_sha" ]; then
                echo "ERROR: --arm blindpod refuses an inherited advice identity: blindpod is" >&2
                echo "  the WITHOUT_ADVICE arm (D-NAME-1) and consumes no artifact, so a" >&2
                echo "  digest reaching it means the control arm was launched from a treated" >&2
                echo "  campaign binding. Refused rather than ignored." >&2
                return 1
            fi
            GOLD_ADVICE_ABS=""
            GOLD_ADVICE_SHA256=""
            GOLD_ARM_ARGS=(--experiment_arm blindpod --no-ml_lit_review_enabled)
            ;;
        *)
            echo "ERROR: unknown --arm '$arm' (campaign arms: ${GOLD_ARMS[*]})" >&2
            return 1 ;;
    esac
}

#: Flags an operator may NOT pass through to the chain: each is either a
#: frozen value (typed once at this boundary), an arm/band/treatment-decided
#: value, or the retention violation R-RETENTION-1 exists to refuse.
#:
#: --llm_config / --llm_model (D-LLM-1, F-LLM-WIRE-1): passthrough tokens are
#: appended AFTER the frozen args and _chain_common.sh's parse loop is
#: last-wins, so a passed-through --llm_config would silently OVERRIDE the
#: campaign's pinned routing — the same defect one layer down. --llm_model is
#: reserved for the reason --max_epochs is: no second model authority may
#: reach the child argv, even one the config already shadows.
#:
#: --enable_chain_incumbent_formal_gates (F-GATE-WIRE-1, #316 B1): the
#: campaign's formal-gate policy is typed ONCE at this boundary and emitted
#: unconditionally by gold_frozen_chain_args. No negative spelling exists
#: downstream, so a passthrough cannot turn the gates OFF — it is reserved
#: for the reason --max_epochs is: no SECOND authority may decide a frozen
#: campaign policy from an operator's command line, even one that is
#: currently redundant. Gate activation is a scientific-policy fact of the
#: campaign, not of the invocation.
#:
#: --required_runtime_profile / --required_runtime_profile_sha256
#: (F-PROFILE-WIRE-1): same last-wins hazard. The declaration enters through
#: the entrypoint's --gold_required_runtime_profile[_sha256], which the
#: dry-run row and the launch manifest RECORD; a passed-through chain-level
#: spelling would rebind the requirement to something no recorded surface
#: names — a pinned profile that the manifest misreports is worse than none.
#:
#: --trial_vram_budget_gb / --formal_vram_budget_gb (D-HW-6): same last-wins
#: hazard, and the reason the reservation matters even though the campaign
#: usually supplies NO ceiling. The operator ceiling enters through the
#: entrypoint's --gold_*_vram_budget_gb, which the dry-run row and the launch
#: manifest RECORD; a passed-through chain-level spelling lands AFTER the
#: bound tokens and would silently win, leaving both recorded surfaces naming
#: a ceiling the run is not using. It also defeats the both-or-neither rule,
#: since a passthrough can rebind one mode alone.
GOLD_RESERVED_PASSTHROUGH=(
    --cleanup_denoised
    --num_iterations --trial_portion --train_portion --eval_portion
    --formal_portion --formal_train_portion --formal_eval_portion
    --max_epochs --trial_max_epochs --formal_max_epochs
    --trial_time_budget_minutes --formal_time_budget_minutes
    --skip_formal_min_delta --bypass_formal_time_budget_min_delta
    --bypass_formal_time_budget_minutes
    --enable_chain_incumbent_formal_gates
    --llm_config --llm_model
    --required_runtime_profile --required_runtime_profile_sha256
    --required_runtime_profile_path
    --trial_vram_budget_gb --formal_vram_budget_gb
    --experiment_arm --ml_lit_review_enabled --no-ml_lit_review_enabled
    # --advice_sha256 (advice-invariant): the chain-level spelling of the
    # treatment identity. Reserved for the reason --llm_config is: the
    # parse loop is last-wins and passthrough tokens are appended AFTER
    # the frozen args, so a passed-through digest would rebind the very
    # value the launch manifest reports -- a pin the manifest misreports
    # is worse than no pin.
    --advice --advice_sha256 --human_advice_file
    --data_scope --health_gate_files --band --workspace --run_name
    --mode --seed_paths --start_iter
    --auto_resume --no_auto_resume --force_fresh
    --validation_fixed_candidate_plan
)

# gold_refuse_reserved_passthrough TOKEN... — refuse any reserved token,
# naming it and the authority that owns it. --cleanup_denoised gets the
# dedicated R-RETENTION-1 message (witness b).
gold_refuse_reserved_passthrough() {
    local tok reserved
    for tok in "$@"; do
        if [ "$tok" = "--cleanup_denoised" ]; then
            echo "ERROR: --cleanup_denoised is refused for campaign chains (R-RETENTION-1," >&2
            echo "  release blocker): official FORMAL execution RETAINS deliverables — a" >&2
            echo "  cleaned formal winner leaves Stage-3 nothing to pool (contract section 1," >&2
            echo "  retention clause). Exploratory/non-campaign paths keep the flag." >&2
            return 1
        fi
        for reserved in "${GOLD_RESERVED_PASSTHROUGH[@]}"; do
            if [ "$tok" = "$reserved" ]; then
                echo "ERROR: $tok is decided by the campaign entrypoint's frozen boundary and" >&2
                echo "  cannot be passed through (_gold_campaign_lib.sh GOLD_RESERVED_PASSTHROUGH)." >&2
                return 1
            fi
        done
    done
    return 0
}

# gold_bind_task_config PATH — validate the task-config authority and set
# GOLD_TASK_CONFIG_ABS + GOLD_TASK_CONFIG_SHA256.
#
# TRANSPORT GAP, recorded rather than papered over: neither run_chain.sh
# nor run_one_iteration.py accepts a --task_config flag; the framework
# reads configs/task_config.yaml from the repository the chain executes in
# (run_chain cd's to the project dir). The binding is therefore VALIDATED
# and RECORDED here (path + sha256 in the launch manifest), and a supplied
# file whose CONTENT differs from the executing repo's is REFUSED — the
# chain would silently execute the repo's copy, which is exactly the
# divergence class F-SCANH-1 names.
gold_bind_task_config() {
    local path="$1" repo_cfg repo_sha
    if [ ! -f "$path" ]; then
        echo "ERROR: --task_config not found: $path" >&2
        return 1
    fi
    GOLD_TASK_CONFIG_ABS="$(cd "$(dirname "$path")" && pwd)/$(basename "$path")"
    GOLD_TASK_CONFIG_SHA256="$(sha256sum "$GOLD_TASK_CONFIG_ABS" | awk '{print $1}')"
    repo_cfg="${GOLD_PROJECT_DIR}/configs/task_config.yaml"
    if [ ! -f "$repo_cfg" ]; then
        echo "ERROR: the executing repository has no configs/task_config.yaml: $repo_cfg" >&2
        return 1
    fi
    repo_sha="$(sha256sum "$repo_cfg" | awk '{print $1}')"
    if [ "$GOLD_TASK_CONFIG_SHA256" != "$repo_sha" ]; then
        echo "ERROR: --task_config content differs from the executing repository's" >&2
        echo "  configs/task_config.yaml, and the chain has NO argv transport for a" >&2
        echo "  task-config path — it would silently execute the repo's copy." >&2
        echo "    supplied: $GOLD_TASK_CONFIG_ABS (sha256 $GOLD_TASK_CONFIG_SHA256)" >&2
        echo "    executes: $repo_cfg (sha256 $repo_sha)" >&2
        echo "  Align the checkout or drop the flag (F-SCANH-1 divergence class)." >&2
        return 1
    fi
}

# gold_workspace_root_check DIR — the persistent-volume root must already
# exist and be writable (fail the whole campaign up-front, not per nohup'd
# band — same rule as the fleet launcher; campaign_preflight.sh owns the
# mount verification).
gold_workspace_root_check() {
    local root="$1"
    if [ -z "$root" ]; then
        echo "ERROR: --workspace_root DIR is required (the persistent campaign root; contract section 1)" >&2
        return 1
    fi
    if [ ! -d "$root" ] || [ ! -w "$root" ]; then
        echo "ERROR: --workspace_root must be an existing writable directory: $root" >&2
        return 1
    fi
}

# gold_refuse_preset_cuda — under the frozen single-resident map the band's
# CUDA_VISIBLE_DEVICES value is a PHYSICAL index; an ambient
# CUDA_VISIBLE_DEVICES would remap it silently (child "0" could mean
# physical 2). Refused in live mode; dry-run prints the map regardless.
gold_refuse_preset_cuda() {
    if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
        echo "ERROR: CUDA_VISIBLE_DEVICES is already set ('${CUDA_VISIBLE_DEVICES}') — the" >&2
        echo "  campaign's frozen band->GPU map (0-3->0, 4-9->1, 10-14->2, 15-19->3," >&2
        echo "  single_resident) assigns PHYSICAL indices per band; an ambient value" >&2
        echo "  would remap them silently. Unset it and relaunch." >&2
        return 1
    fi
}

#: Interval between the band watcher's persisted-state polls (seconds).
GOLD_WATCH_INTERVAL_SECONDS="${GOLD_WATCH_INTERVAL_SECONDS:-120}"
#: Consecutive run_chain invocations with no newly COMMITTED iteration
#: before a band loop stops retrying (mirrors --max_failed_iterations 3).
GOLD_MAX_NO_PROGRESS_CYCLES="${GOLD_MAX_NO_PROGRESS_CYCLES:-3}"
#: Marker written into the chain STOP file when the BAND ORCHESTRATOR
#: requests the stop (FCNet+2 rule satisfied); distinguishes our graceful
#: stop from an operator's own STOP file, which is never removed by us.
GOLD_STOP_MARKER="gold_stage1_stop_rule_satisfied"
