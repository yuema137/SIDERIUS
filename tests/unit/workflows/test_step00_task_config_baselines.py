"""Step-00 CFG-1 / CFG-2 / CFG-3a / CFG-3b — task-config baselines.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.2. The resolved dict (CFG-1) and the rendered strings (CFG-2) are
DISTINCT drift surfaces: ``task_description`` is stripped by the loader
while the forward-contract note fields are stripped only in the renderer.

Hazards honored (design §13.2): explicit absolute config paths (the
loader's default is cwd-relative); the loader cache is cleared around each
test (it returns a SHARED MUTABLE dict — these tests never mutate it); no
coupling to ``tidmad_data_config.yaml`` machine state.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from agent.schemas.task_config import ForwardContract
from tests.helpers.golden import assert_golden, assert_json_golden
from workflows.task_config import (
    _clear_cache_for_tests,
    get_task_description,
    load_task_config,
    render_forward_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_CONFIG_YAML = REPO_ROOT / "configs" / "task_config.yaml"
LIT_REVIEW_YAML = REPO_ROOT / "configs" / "lit_review_config.yaml"
GOLDENS = Path(__file__).parent / "goldens"


def _load_shipped() -> dict:
    _clear_cache_for_tests()
    try:
        return load_task_config(str(TASK_CONFIG_YAML))
    finally:
        _clear_cache_for_tests()


class TestCFG1ResolvedTaskConfig:
    def test_resolved_shipped_config_deep_equal(self):
        """CFG-1 (Type 2): the full resolved dict of the SHIPPED
        ``configs/task_config.yaml`` through the production loader —
        previously only truthiness + ``num_classes == 256`` were pinned."""
        cfg = _load_shipped()
        assert_json_golden(
            copy.deepcopy(cfg),
            GOLDENS / "cfg1_task_config_resolved.json",
            surface="CFG-1 resolved task config",
        )


class TestCFG2RenderedTaskStrings:
    def test_task_description_render(self):
        cfg = _load_shipped()
        assert_golden(
            get_task_description(cfg),
            GOLDENS / "cfg2_task_description.txt",
            surface="CFG-2 rendered task description",
        )

    def test_forward_contract_render(self):
        """The shipped ``{FORWARD_CONTRACT}`` block was pinned by NOTHING
        (renderer tests use a synthetic contract that differs from the
        shipped file). The renderer's ordering, ``rstrip(" —")`` and note
        handling are load-bearing."""
        cfg = _load_shipped()
        fc = ForwardContract(**cfg["forward_contract"])
        assert_golden(
            render_forward_contract(fc),
            GOLDENS / "cfg2_forward_contract_block.txt",
            surface="CFG-2 rendered forward contract",
        )


class TestCFG3LitReviewConfig:
    def test_cfg3a_lit_review_declares_no_task_description(self):
        """CFG-3a, REWRITTEN at Step 04b — the duplicate is gone.

        This pin used to assert the two declarations stayed byte-identical
        ("catch SILENT DRIFT ... until step 04 collapses the duplication").
        Step 04b performed that collapse, so the drift it guarded is now
        structurally impossible and the old assertion would have *required*
        the duplicate to exist. Rewritten around the invariant that replaced
        it rather than deleted, per the same reasoning that motivated it:
        the lit-review config must not regain its own authority.

        The check is on the PARSED mapping's top-level keys, never on the
        file text — the file legitimately explains in prose where the
        description now comes from, and a substring scan would fire on that
        comment.
        """
        b = yaml.safe_load(LIT_REVIEW_YAML.read_text(encoding="utf-8"))
        assert "task_description" not in b, (
            "configs/lit_review_config.yaml declares a top-level "
            "`task_description` again — Step 04b made "
            "configs/task_config.yaml the single source and "
            "_build_lit_review_input no longer reads this key, so a "
            "declaration here is a silent second authority that would drift "
            "unnoticed. Delete it; edit configs/task_config.yaml instead."
        )

    def test_cfg3a_task_config_remains_the_one_declaration(self):
        """The other half: exactly one legitimate source, not zero.

        A guard that only forbids declarations would pass on a repository
        that had lost the canonical one too.
        """
        a = yaml.safe_load(TASK_CONFIG_YAML.read_text(encoding="utf-8"))
        assert str(a.get("task_description") or "").strip() != ""

    def test_cfg3b_task_semantic_fields_deep_equal(self):
        """CFG-3b (Type 2): the lit-review config's own task-semantic
        fields (root papers, dynamic_search, verbosity, synthesis,
        confidence rubric) — pinned by nothing before Step 00."""
        b = yaml.safe_load(LIT_REVIEW_YAML.read_text(encoding="utf-8"))
        semantic = {
            k: b[k]
            for k in (
                "enabled",
                "root_papers",
                "dynamic_search",
                "findings_verbosity",
                "synthesis",
                "confidence_rubric",
            )
        }
        assert_json_golden(
            json.loads(json.dumps(semantic)),
            GOLDENS / "cfg3b_lit_review_task_semantics.json",
            surface="CFG-3b lit-review task-semantic fields",
        )
