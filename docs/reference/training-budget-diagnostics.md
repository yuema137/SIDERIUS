# Training budget evidence

A configured time budget is currently an admission ceiling. The executor runs
the resolved epoch count and does not extend it merely because time remains.
This reference documents current behavior; it does not introduce a dynamic
training policy or change validation cadence, portions, epoch caps or watchdogs.

The training child prints a structured `[training_budget]` JSON entry before
its first optimizer step and after training timing verification. It reports
the fixed epoch/step horizon, attempt budget, measured prediction when
available, and phase predictions still missing. A projection below 10% of the
attempt budget is labelled `LOW_TRAINING_BUDGET_PROJECTION`. That threshold is
only a diagnostic, never an admission rule or a request to consume the rest.
Missing validation, inference or scoring predictions do not count as zero;
the report cannot establish unused whole-attempt budget or convergence.

Validation timing now includes DataLoader.next(), transfer, forward/loss and
batch observations. Stability and workload prediction use per-sample time;
measurement evidence minimums and caps use the actual batch elapsed time.
This distinction matters when batches contain many samples or an unequal tail.

Composed generic inference records its materialized sample workload, adaptive
measurement and actual complete pass (including deliverable writing) in the
existing runtime observation sidecar. Batch observations include reading,
forward, CPU transfer and writer consumption while yielding predictions.
Writer final flush after stream exhaustion is included in actual duration,
but has no advance estimate; prediction metadata names this limitation.
Short or unstable scopes retain failed/incomplete measurement evidence rather
than invent a prediction. Model loading before this generic pass is not part
of the pass's actual duration.

Training phase wall time includes its loader work; it is not pure GPU kernel
time. CUDA allocated/reserved peaks are memory evidence, not GPU utilization
or proof that a larger model would improve scientific quality. Future policy
changes should use corrected phase measurements and explicit convergence and
budget semantics, rather than simply increasing every epoch count.

## Late stability and runtime refusal feedback

The verifier retains evidence across the training and validation passes that the
experiment actually requested. It never adds epochs to meet a measurement
minimum. If the workload ends before sufficient evidence exists, verification
remains unsuccessful.

The distribution fallback considers retained steady elapsed time and the
physical observations still available within the configured observation cap.
It does not assume that stability was detected at the earliest possible step.
Its prediction window retains the larger of the configured distribution count
and the current required steady count, including any prior-drift extension.
Normal count, time, wall-cap and absolute-unit limits remain in force.

Before accepting an ordinary or fallback measurement, a distribution-block
check ensures that its later window did not conceal a distinct earlier rate
regime. It starts at the first observation window whose maximum is within
`pathological_factor` of its median, and extends backward through contiguous
observations within that same bound. This excludes an initial warm-up outlier;
it does not select the smallest median seen during verification. Establishing
observed support does not require that the earlier rates form a stable plateau;
stability is required separately for the proposed prediction.

Every subsequent observation remains in the comparison. Each side of a split
must contain at least `steady.min_steps_to_detect` observations. A sustained
shift requires every later rate to exceed the earlier observed maximum and the
later median to exceed `pathological_factor` times the earlier median. Recurrent
expensive batches therefore remain part of the reference distribution. The
existing plateau-based slow-streak guard is unchanged and can reject earlier.

This check establishes only the stated separation of observed blocks. Overlap
is inconclusive, not proof of unchanged future runtime. No finite trace can
exclude every rare-tail false alarm or predict changes after verification ends.
Existing observation/time limits and execution-budget enforcement still apply.

In-subprocess rejection memory uses `runtime_feedback_version="facts-v1"`.
`memory_update` reports the recorded admission reason and distinguishes a
budget/allocation rejection from failure to establish a reliable prediction.
Missing legacy cause codes remain explicitly unclassified. It preserves attempt
consumption and supplies no fixed workload-reduction strategy. Raw admission
facts and the existing conclusion remain available. Historical presentation is
an explicitly versioned consumer plugin concern, not an infra execution mode.
