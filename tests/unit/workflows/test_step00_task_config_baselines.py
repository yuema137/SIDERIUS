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
    def test_cfg3a_task_description_duplicate_byte_equal(self):
        """CFG-3a (Type 1, MIGRATION PARITY — NOT FINAL FRAMEWORK
        CONTRACT): ``configs/lit_review_config.yaml`` duplicates
        ``configs/task_config.yaml``'s ``task_description`` on a SEPARATE
        load path (``workflows/model_exploration.py``) that never touches
        ``task_config.py``. The duplication is registered debt (collapses
        at roadmap step 04); this pin exists to catch SILENT DRIFT between
        the two copies during migration, not to bless the duplicate."""
        a = yaml.safe_load(TASK_CONFIG_YAML.read_text(encoding="utf-8"))
        b = yaml.safe_load(LIT_REVIEW_YAML.read_text(encoding="utf-8"))
        assert a["task_description"] == b["task_description"], (
            "task_description drifted between configs/task_config.yaml and "
            "configs/lit_review_config.yaml — the two copies must stay "
            "byte-identical until step 04 collapses the duplication"
        )

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
