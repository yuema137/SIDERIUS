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
