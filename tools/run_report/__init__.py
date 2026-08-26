"""Static report renderer over :mod:`execute_tools.run_report`.

Step 12 / PR-12e, workstream R. Design §V.5: *a mature example must NOT
require the dashboard to be understood.* This package is the lightweight,
portable way to see a completed run — one directory of self-contained HTML
and PNG plus a machine-readable ``report.json``.

    python -m tools.run_report --workspace <chain_workspace_dir> --out <dir>
    python -m tools.run_report --run-output <run_output_*.json> --out <dir>

**These flags are FROZEN.** Three example packs publish this exact command in
their READMEs, and workstream D consumes the contract read-only.

Why it lives in ``tools/`` and not in a production package
-----------------------------------------------------------
``tools/`` is deliberately not a production directory: nothing under
``agent/``, ``core/``, ``execute_tools/``, ``nodes/`` or ``workflows/``
imports it, so a rendering change can never reach the training, scoring or
chain path. The SEMANTICS live in ``execute_tools/run_report.py``; this
package only draws them. That split is §V.5's "the view is never a semantic
authority", made structural.

What this renderer may not do
------------------------------
* it must not decide metric direction — it reads the direction words the
  projection already asked ``MetricOrder`` for;
* it must not label a training objective "loss" — it prints the projection's
  ``objective_kind``;
* it must not contain task dispatch. There is no task name in this package.
  Waveform / image / video / spectrum presentation belongs to the example
  pack, beside this output (§V.4).
"""

from __future__ import annotations

from tools.run_report.cli import main

__all__ = ["main"]
