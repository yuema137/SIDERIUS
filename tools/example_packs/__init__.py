"""PR0 example-pack GENERATION / PROJECTION tooling — not a runtime component.

Design: ``docs/design/generic_framework_upgrade/
step_07_tuner_policy_and_training_diagnostics/pr0_persistent_example_baseline.md``
(§3.1, §3.6, §13.1 OD-PR0-1).

What this package is
    The tooling that (a) PROJECTS what production already resolves for the
    TIDMAD task into read-only resolved snapshots under
    ``examples/tidmad/resolved/`` and (b) DERIVES the identity manifests and
    the pack-owned L0/L1 declarations of the two contrast packs
    (``examples/oxford_iiit_pet/``, ``examples/davis_future_prediction/``).
    Every semantic value it writes is either read from a production
    authority (TIDMAD) or is an instance value the pack owns (roadmap
    §22.23.1); it interprets no rule.

What this package is NOT
    * not a runtime subsystem — no production package imports it, and
      ``tests/unit/examples/test_pack_governance.py`` guards that permanently;
    * not a generic dataset loader, reader or composition framework;
    * not something D14 / Step 12 are obliged to reuse (OD-PR0-1): any logic
      that genuinely belongs in the framework migrates by convergence and
      source evidence, never because it happens to live here.

Consumers: the CI acceptance tests under ``tests/unit/examples/`` and an
operator regenerating a pack by hand (``python -m tools.example_packs.<pack>``).
"""
