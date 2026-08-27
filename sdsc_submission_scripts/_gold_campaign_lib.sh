#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Gold campaign — SHARED LIBRARY (source, do not exec)
# ---------------------------------------------------------------------------
# Role   : the ONE shared boundary where the campaign's frozen authorities
#          are typed (D-ARCH-1, F-LAUNCH-1). Sourced by run_gold_campaign.sh
#          and by every stage script under it; NEVER by the X9 launchers.
#
# Owns   : the frozen-value table (the twelve chain-boundary values from
#          docs/campaign/official_campaign_decisions.yaml — D-BUD-2 horizon,
#          D-BUD-6 epochs, D-BUD-7 trial portions, D-BUD-8 formal portions,
#          D-BUD-11/13 time budgets, P6-A skip delta, P6-B bypass delta),
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
# THE FROZEN-VALUE TABLE — the twelve typed chain-boundary values.
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
# max_epochs=1 — DECLARED LIMITATION (D-BUD-6): the frozen campaign semantics
# are trial_max_epochs=2 / formal_max_epochs=1, but the chain exposes ONE
# mode-agnostic ceiling (`run_one_iteration.py --max_epochs`, "Hard cap on
# epochs per round") and no trial/formal split exists anywhere in the
# codebase ("historical_state", D-BUD-6). 1 is the SAFE value: it can violate
# neither frozen ceiling; 2 could leak a second epoch into a formal round.
# The trial-2 allowance is unreachable until the split lands (release lane).
# Do NOT invent a second knob here.
GOLD_FROZEN_ROWS=(
    "num_iterations=20"
    "trial_portion=0.1"
    "train_portion=0.1"
    "eval_portion=0.01"
    "formal_portion=1.0"
    "formal_train_portion=0.1"
    "formal_eval_portion=0.1"
    "max_epochs=1"
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
        max_epochs trial_time_budget_minutes formal_time_budget_minutes \
        skip_formal_min_delta bypass_formal_time_budget_min_delta; do
        v="$(gold_frozen_value "$key")" || return 1
        GOLD_FROZEN_CHAIN_ARGS+=("--${key}" "$v")
    done
    gold_bypass_ceiling_args
    GOLD_FROZEN_CHAIN_ARGS+=(${GOLD_BYPASS_CEILING_ARGS[@]+"${GOLD_BYPASS_CEILING_ARGS[@]}"})
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
    local arm="$1" advice="$2" advice_abs
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
            GOLD_ARM_ARGS=(--experiment_arm goldpod --no-ml_lit_review_enabled --advice "$advice_abs")
            ;;
        blindpod)
            if [ -n "$advice" ]; then
                echo "ERROR: --arm blindpod refuses --gold_advice_file: blindpod is the" >&2
                echo "  WITHOUT_ADVICE arm (D-NAME-1); its treatment is the EXPLICIT absence" >&2
                echo "  of the artifact (plan section 5.6)." >&2
                return 1
            fi
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
GOLD_RESERVED_PASSTHROUGH=(
    --cleanup_denoised
    --num_iterations --trial_portion --train_portion --eval_portion
    --formal_portion --formal_train_portion --formal_eval_portion
    --max_epochs --trial_time_budget_minutes --formal_time_budget_minutes
    --skip_formal_min_delta --bypass_formal_time_budget_min_delta
    --bypass_formal_time_budget_minutes
    --experiment_arm --ml_lit_review_enabled --no-ml_lit_review_enabled
    --advice --human_advice_file
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
