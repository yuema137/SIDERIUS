"""Native training argument declarations, shared with explicit deployment launchers.

Parsing performs no training, plugin imports, file reads or authorization. The
training engine remains the owner of semantic validation and execution. Keep one
parser so deployment adapters preserve the existing native CLI interpretation.
"""

import argparse


def build_training_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_cfg", type=str, required=True)
    parser.add_argument("--train_cfg", type=str, required=True)
    parser.add_argument("--loss_cfg", type=str, required=True)
    parser.add_argument("--custom_loss_contract_json", type=str, default=None)
    parser.add_argument(
        "--model_io_json",
        type=str,
        default=None,
        help=(
            "Path to a resolved Model-I/O contract JSON (axes, roles, "
            "dimensions, input dtype admissibility). OMITTED means the "
            "Regime-A compatibility adapter: each model's own declaration, "
            "else the site's historical dtype — exactly as before this flag "
            "existed. SUPPLIED but broken fails closed; it never falls back "
            "to a fabricated contract."
        ),
    )
    parser.add_argument(
        "--dataset_profile_json",
        type=str,
        default=None,
        help=(
            "Path to a resolved Dataset Profile JSON (topology, geometry, "
            "channel identity, value encoding). OMITTED delegates to the "
            "active task binding and refuses when none exists. SUPPLIED but "
            "broken fails closed."
        ),
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        default=None,
        help="Caller-selected physical dataset directory. No implicit fallback.",
    )
    parser.add_argument("--sandbox_dir", type=str, default=None, help="Sandbox output directory.")
    parser.add_argument("--file_index", type=int, default=6)
    parser.add_argument(
        "--task_scope_ref",
        type=str,
        default=None,
        help="Step 12 / PR-12bc B6: path to this attempt's TASK-BUILT training "
        "scope artifact, emitted by the parent FROM its resolved binding only — "
        "never an operator flag. SUPPLIED -> the artifact is digest-verified and "
        "deserialized by the transported implementation, and the regime-A "
        "TidmadScope fallback is NOT reached. ABSENT -> regime-A, byte-identical.",
    )
    parser.add_argument(
        "--task_scope_digest",
        type=str,
        default=None,
        help="sha256 of the training scope artifact, transported OUT OF BAND so "
        "the artifact is never asked to vouch for itself. Required with "
        "--task_scope_ref.",
    )
    parser.add_argument(
        "--task_eval_scope_ref",
        type=str,
        default=None,
        help="The EVALUATION leg's artifact — same rule, same verification.",
    )
    parser.add_argument(
        "--task_eval_scope_digest",
        type=str,
        default=None,
        help="The evaluation leg's out-of-band sha256.",
    )
    parser.add_argument("--exp_id", type=str, default="default_exp")
    parser.add_argument(
        "--run_name", type=str, default="test_run", help="Run name for the auto-exploration."
    )
    parser.add_argument(
        "--sample_set_json",
        type=str,
        default=None,
        help="Path to SampleSet JSON for trial mode. Overrides --file_index.",
    )
    parser.add_argument(
        "--eval_sample_set_json",
        type=str,
        default=None,
        help=(
            "Step 07a: path to the tuner's EXISTING run-bound eval SampleSet JSON "
            "({file_index: [segment_indices]}), addressed on the VALIDATION file "
            "family. Streaming mode only (with --sample_set_json). SUPPLIED → the R3 "
            "validation pass runs after every completed epoch and the declared scope "
            "must materialize exactly (fails closed otherwise). SUPPLIED but "
            "unreadable / not a mapping → ValueError naming the path. ABSENT → no "
            "validation pass; R3 is honestly absent (legacy tolerance)."
        ),
    )
    parser.add_argument(
        "--validation_executor_json",
        default=None,
        help="Explicit deployment client/settings JSON; absent preserves native local validation.",
    )
    parser.add_argument(
        "--validation_requested_rows",
        type=int,
        default=None,
        help=(
            "Step 12 / PR-12d (B9): the CALLER's declared validation row count "
            "for the EXPLICIT eval-scope leg. Required whenever "
            "--task_eval_scope_ref is supplied and --eval_sample_set_json is "
            "not: the engine refuses an unvalidated R3, and TrainingHistory "
            "asserts requested == materialized. The declaration comes from the "
            "PARENT so that check compares two sides of the process boundary "
            "rather than the pass against itself. Refused crosswise with "
            "--eval_sample_set_json, which is the regime-A leg whose "
            "declaration is the preflight."
        ),
    )
    parser.add_argument(
        "--train_portion",
        type=float,
        default=None,
        help="Fraction of segments per file to subsample each epoch (0.01-1.0). "
        "When None, uses all segments in the scope.",
    )
    parser.add_argument(
        "--freeze_subsample",
        action="store_true",
        help="Use the same subsample every epoch instead of resampling.",
    )
    parser.add_argument(
        "--train_base_seed",
        type=int,
        default=None,
        help="Base seed for per-epoch subsampling. Epoch n uses seed = base + n. "
        "When None, derived from exp_id hash.",
    )
    parser.add_argument(
        "--order_strategy",
        type=str,
        default="shuffle",
        choices=["shuffle", "sequential"],
        help="RESOLVED training sample visitation order. 'shuffle' (default) is a "
        "global uniform shuffle; 'sequential' visits file blocks in order with "
        "rows shuffled within each block. Already resolved from the agent "
        "proposal and any operator override — this process does not re-resolve.",
    )
    parser.add_argument(
        "--file_order_json",
        type=str,
        default=None,
        help="Path to a JSON list giving the RESOLVED file visitation order for "
        "--order_strategy sequential. Must be a permutation of the sample set's "
        "files. Omit for ascending file index.",
    )
    parser.add_argument(
        "--runtime_observation_out",
        type=str,
        default=None,
        help="RT2-B: path for the runtime-verification observation sidecar "
        "(streaming mode only). When set, the in-subprocess verification "
        "session records setup/admission/actuals progressively to this file.",
    )
    parser.add_argument(
        "--runtime_policy_json",
        type=str,
        default=None,
        help="RT2-B: path to a RuntimeControlPolicy JSON (operator budget). "
        "Only meaningful together with --runtime_observation_out.",
    )
    parser.add_argument(
        "--task_data_path_id",
        type=str,
        default=None,
        help="D14-1: the child side of the task-data-path transport. Emitted "
        "by the parent process FROM its resolved run binding only — never an "
        "operator flag. SUPPLIED -> explicit binding (an unknown id fails "
        "closed, never falls back); ABSENT -> regime-A (TIDMAD compatibility).",
    )
    parser.add_argument(
        "--task_data_path_identity",
        type=str,
        default=None,
        help="Step 12 / PR-12bc C2: the PARENT-PINNED IDENTITY of the implementation named by --task_data_path_id. The id says WHICH implementation; this says WHICH CODE. Verified BEFORE the implementation is consumed, because a registry hit is never proof of identity — a stale registration answers to the right name while running different bytes. ABSENT -> a parent that predates this transport made no claim, and a child must not invent one.",
    )
    parser.add_argument(
        "--task_manifest",
        type=str,
        default=None,
        help="Step 12 / PR-12bc C3: the composed run's task-composition manifest, emitted by the parent FROM its resolved run binding only "
        "— never an operator flag. SUPPLIED -> a transported id that is not built into this child is composed from the run's OWN declaration, through the same authority the parent used, which is what lets an "
        "OUT-OF-TREE task reach a training or inference subprocess. ABSENT -> the id must already be registered here.",
    )
    return parser
