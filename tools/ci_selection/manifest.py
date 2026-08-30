"""The exceptions the AST cannot derive, and the fail-closed rules.

Kept as Python rather than YAML on purpose: every entry below carries the reason
it exists, and a reason is the part that rots first when it lives in a data file
nobody reads. `tests/unit/tools/ci_selection/` asserts every path here still
resolves, so a rename cannot orphan a rule silently.

**This is not wired into CI.** See `resolver.py`.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. ALWAYS-ON — cheaper to run unconditionally than to reason about
# ---------------------------------------------------------------------------
#: Their INPUT is the repository. `test_no_hardcoded_device_literals` scans
#: `core/`, `agent/`, `nodes/`; the launcher and self-reference guards scan
#: `tests/` itself; `test_gate_standard_contract` reads a doc. Selecting them
#: is not possible in principle, and at ~134 cases they are cheaper than the
#: logic that would try. Two of them scan `tests/`, which is why ANY test-file
#: change also runs this block — a property this list gives for free.
ALWAYS_ON: tuple[str, ...] = (
    "tests/unit/guardrails/",
    "tests/unit/test_repo_hygiene.py",
    "tests/unit/ml_models/test_registry_population_is_self_healing.py",
    "tests/unit/agent/llm_bridge/test_all_calls_labeled.py",
    "tests/unit/nodes/test_node_public_boundary.py",
)

# ---------------------------------------------------------------------------
# 2. HUBS — fan out so widely that selecting is a lie
# ---------------------------------------------------------------------------
#: Measured depth-1 reach: `agent/schemas/hyperparam_tuning.py` alone selects
#: ~4,059 of 9,697 cases; `execute_tools/dataset_config.py` ~59% of the suite;
#: `core/runtime_control/records.py` ~3,351. A "selective" run of 60-75% of the
#: suite carries all of the risk and almost none of the benefit, so these run
#: everything and say so.
HUBS: tuple[str, ...] = (
    "agent/schemas/",
    "core/runtime_control/records.py",
    "core/runtime_control/estimate_types.py",
    "execute_tools/dataset_config.py",
    "execute_tools/scoring_utils.py",
)

# ---------------------------------------------------------------------------
# 3. FULL-SUITE TRIGGERS — infrastructure, or the selector itself
# ---------------------------------------------------------------------------
#: A broken selector can select "nothing" and report green, so any change to it
#: must be validated against everything. The root conftests are autouse
#: (`tests/unit/conftest.py` installs `forbid_real_heavy_subprocess`), so their
#: blast radius is the whole suite by construction.
FULL_SUITE_TRIGGERS: tuple[str, ...] = (
    "tools/ci_selection/",
    "tests/unit/tools/ci_selection/",
    "tests/conftest.py",
    "tests/unit/conftest.py",
    "tests/helpers/",
    "pyproject.toml",
    "pyrightconfig.json",
    "uv.lock",
    ".github/workflows/",
)

# ---------------------------------------------------------------------------
# 4. DIRECTORY-SCAN DECLARATIONS — what the AST provably cannot resolve
# ---------------------------------------------------------------------------
#: These modules read a directory built from a NON-CONSTANT root, so no literal
#: path edge exists. `tests/helpers/tuner_source.py:32` is the proof case:
#: `Path(__file__).resolve().parents[2] / "nodes" / "ml_hyperparameter_tune_agent"`,
#: which 31 modules / 838 cases depend on. Declared, because derivation cannot.
DIRECTORY_SCANS: dict[str, tuple[str, ...]] = {
    "tests/unit/guardrails/test_no_hardcoded_device_literals.py": ("core/", "agent/", "nodes/"),
    "tests/unit/guardrails/test_no_model_name_branches.py": (
        "agent/skills/evaluate_vram_skill/",
        "agent/skills/training_skill/estimator.py",
        "agent/skills/inference_skill/estimator.py",
        "core/inference_defaults.py",
        "core/runtime_control/gpu_measurement_worker_main.py",
    ),
    "tests/unit/agent/llm_bridge/test_all_calls_labeled.py": ("nodes/",),
    # Step 12 / PR-12e -- the presentation-layer ordering census. It derives NO
    # import edge (its subjects are `.js` and `.html`), and the selector's
    # `_production_files()` indexes only py/md/txt/sh/json/jsonl/yaml, so its
    # literal path references resolve to nothing either. Without this entry the
    # census is unreachable: a change to `app.js` would NOT run the guard whose
    # entire purpose is to constrain `app.js`.
    #
    # This is the F-12e-UX-8 shape ONE LEVEL UP. That defect was a census whose
    # file set was `rglob("*.py")` while the code it guarded lived in `app.js`;
    # this would have been a SELECTOR whose file set has the same blind spot.
    # The fix for a census that cannot see the presentation layer is worth
    # nothing if the thing that decides whether to RUN it shares the blindness.
    #
    # SCOPED TO `dashboard/static/`, NOT `dashboard/`, and the narrowing is
    # load-bearing rather than tidiness. `resolver.py:295` consults AREA_OWNERS
    # only `if not direct`, so ANY directory scan covering a file that nothing
    # imports SUPPRESSES that file's area suite. `dashboard/main.py` is exactly
    # such a file (a FastAPI entry point with no importer), and scanning
    # `dashboard/` broadly made a change to it stop selecting
    # `tests/unit/dashboard/` -- verified: it turned
    # `test_an_area_owned_module_selects_its_area_not_everything` RED. Scoping
    # to the presentation subtree keeps the census reachable while leaving
    # every area fallback intact. The underlying "an explicit scan replaces
    # rather than augments the area owner" behaviour is recorded as a finding.
    "tests/unit/execute_tools/test_step12_pr12e_presentation_ordering_census.py": (
        "dashboard/static/",
    ),
    # Reaches the tuner through `importlib` with a computed name (`:36`), which
    # the AST cannot resolve -- found by the mutation oracle, not by review: a
    # change to `policy.py` would otherwise NOT have run the suite guarding its
    # MetricOrder consumers.
    "tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c2_order_consumers.py": (
        "nodes/ml_hyperparameter_tune_agent/",
        "execute_tools/metric_order.py",
    ),
    # Helper -> production declarations. A helper is the indirection that HIDES
    # a production dependency, so each one states what it reaches.
    "tests/helpers/step00_pseudo_iteration.py": ("nodes/ml_hyperparameter_tune_agent/",),
    "tests/helpers/tuner_source.py": ("nodes/ml_hyperparameter_tune_agent/",),
    # Imports the focused private module through a computed importlib name, so
    # the AST cannot derive the production edge.
    "tests/unit/nodes/ml_hyperparameter_tune_agent/test_issue_384_probe_data.py": (
        "nodes/ml_hyperparameter_tune_agent/probe_data.py",
    ),
}

# ---------------------------------------------------------------------------
# 5. CONFTEST SCOPES — a conftest change selects its whole directory
# ---------------------------------------------------------------------------
CONFTEST_SCOPES: tuple[str, ...] = (
    "tests/unit/agent/tune_ml_hyperparam_agent/conftest.py",
    "tests/unit/execute_tools/health_checks/conftest.py",
    "tests/unit/tools/claude_hooks/conftest.py",
)

# ---------------------------------------------------------------------------
# 6. GATE OWNERSHIP — advisory output only; CI must NEVER trigger a Gate
# ---------------------------------------------------------------------------
#: Gates cost money and need operator approval
#: (`docs/gates/gate_testing_standard.md:148`). This maps a changed area to the
#: Gate the standard's assignment table requires, so a PR can SAY what it owes.
#: `tests/unit/guardrails/test_gate_standard_contract.py` parses that document;
#: this table must be checked against it rather than restating it from memory.
GATE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "agent/prompts.py": ("gate1",),
    "agent/prompt_templates/": ("gate1",),
    "nodes/ml_model_proposal_agent/": ("gate1",),
    "nodes/ml_model_implementor/": ("gate1", "gate2-at-checkpoint"),
    "nodes/ml_code_validator_agent/": ("gate1", "gate2-at-checkpoint"),
    "nodes/result_interpretation_agent/": ("gate1",),
    "workflows/": ("gate1", "gate2-at-checkpoint"),
    "nodes/ml_hyperparameter_tune_agent/": ("gate2",),
    "core/runtime_control/": ("gate2",),
    "core/sandbox_executor.py": ("gate2",),
    "execute_tools/": ("gate2",),
    "ml_models/": ("gate2",),
    "sdsc_submission_scripts/": ("gate2",),
    "scripts/": ("gate2",),
    "dashboard/": (),
    "examples/": (),
    "tools/": (),
}

# ---------------------------------------------------------------------------
# 7. AREA OWNERSHIP — the fallback for a production file with no derived edge
# ---------------------------------------------------------------------------
#: A production module nothing imports is not "unknown": its AREA still has an
#: owning suite. Falling back to the whole repository there is noise, not
#: safety, and noise is what makes a selector get switched off.
#:
#: Ordered longest-prefix-first. Only a path matching NOTHING here, and having
#: no derived edge, is genuinely unmapped and runs everything.
AREA_OWNERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dashboard/", ("tests/unit/dashboard/",)),
    ("tools/example_packs/", ("tests/unit/examples/", "tests/unit/tools/")),
    ("tools/claude_hooks/", ("tests/unit/tools/claude_hooks/",)),
    ("examples/", ("tests/unit/examples/",)),
    ("sdsc_submission_scripts/", ("tests/unit/sdsc_submission_scripts/",)),
    ("scripts/", ("tests/unit/scripts/",)),
    ("workflows/", ("tests/unit/workflows/",)),
    ("ml_models/", ("tests/unit/ml_models/",)),
    ("execute_tools/", ("tests/unit/execute_tools/",)),
    ("core/", ("tests/unit/core/",)),
    ("nodes/", ("tests/unit/agent/", "tests/unit/nodes/")),
    ("agent/", ("tests/unit/agent/",)),
)

#: Suffixes that CANNOT be imported — they reach a test only by a literal path
#: read, and the AST pass finds every one of those. So "no inbound edge" is
#: KNOWLEDGE for these, not ignorance: nothing can be affected, and running the
#: full suite would be pure noise. Contrast an importable `.py`, where a
#: dynamic import could hide a real dependency.
NON_IMPORTABLE_SUFFIXES: tuple[str, ...] = (".md", ".txt", ".rst", ".csv")

#: Docs are ORDINARY INPUTS, not inert. `test_gate_standard_contract.py:31`
#: reads `docs/gates/gate_testing_standard.md`; ten-plus further `.md` files
#: under `docs/`, `examples/`, `reference_data/` and `reports/` are read by
#: tests. A `paths-ignore: ['**.md']` — the first optimisation anyone reaches
#: for — would skip CI on a change that breaks the Gate-standard contract.
DOCS_ARE_INPUTS = True
