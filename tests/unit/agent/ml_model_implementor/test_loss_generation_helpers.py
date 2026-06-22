"""
Unit tests for the L4a deterministic loss-generation helpers in
``nodes/ml_model_implementor/ml_model_implementor.py``:

  - ``_loss_class_name`` (snake_case → CamelCase)
  - ``_assemble_loss_plugin`` (template assembly from LLM JSON)
  - ``_dummy_tensor_validate_loss`` (post-assembly forward-pass check)
  - presence of the 3 module-level prompt constants
    (``IMPLEMENTOR_LOSS_REASONING_PROMPT``, ``..._CODE_PROMPT``,
    ``..._REPAIR_PROMPT``)

These pieces are pure Python — no LLM bridge, no registry write, no
``run()`` orchestration. The bridge-mocked end-to-end tests live in
``test_loss_generation_e2e.py`` (added in L4b).

See ``docs/design/enable_loss_inventory.md`` § Commit L4.
"""

from __future__ import annotations

from nodes.ml_model_implementor.ml_model_implementor import (
    IMPLEMENTOR_LOSS_CODE_PROMPT,
    IMPLEMENTOR_LOSS_REASONING_PROMPT,
    IMPLEMENTOR_LOSS_REPAIR_PROMPT,
    LOSS_PLUGIN_TEMPLATE,
    _assemble_loss_plugin,
    _dummy_tensor_validate_loss,
    _loss_class_name,
)

# ---------------------------------------------------------------------------
# A minimal "good" code dict that mirrors what a well-behaved LLM produces.
# Cross-entropy is the simplest valid loss for the [B,256,T] / [B,T] contract.
# ---------------------------------------------------------------------------

GOOD_CODE = {
    "extra_imports": "",
    "config_fields_code": "    label_smoothing: float = Field(default=0.0, ge=0.0, le=0.5)",
    "config_validators_code": "",
    "config_fields": {"label_smoothing": 0.0},
    "init_body": "        self.label_smoothing = config.label_smoothing",
    "forward_body": (
        "        return F.cross_entropy(inputs, targets, label_smoothing=self.label_smoothing)"
    ),
}


# ---------------------------------------------------------------------------
# _loss_class_name
# ---------------------------------------------------------------------------


class TestLossClassName:
    def test_single_word(self):
        assert _loss_class_name("focal") == "Focal"

    def test_two_words(self):
        assert _loss_class_name("focal_cw") == "FocalCw"

    def test_three_words(self):
        assert _loss_class_name("snr_weighted_mse") == "SnrWeightedMse"

    def test_already_camel_kept_as_is(self):
        # Edge case: input with no underscores stays as-is (only first letter
        # capitalised). Documents current behaviour — not a feature spec.
        assert _loss_class_name("FocalCW") == "Focalcw"


# ---------------------------------------------------------------------------
# _assemble_loss_plugin — assembly contract
# ---------------------------------------------------------------------------


class TestAssembleLossPlugin:
    def test_assembled_source_parses_as_python(self):
        """The assembled file must be syntactically valid Python regardless
        of which prompt constraints the LLM forgets later — this is the
        first line of defence."""
        import ast

        src = _assemble_loss_plugin("ce", "Cross-entropy loss.", GOOD_CODE)
        ast.parse(src)  # raises SyntaxError on failure

    def test_assembled_source_declares_three_required_constants(self):
        """The 3 required PLUGIN_LOSS_* constants are template-owned. The
        LLM cannot accidentally omit them."""
        src = _assemble_loss_plugin("ce", "Cross-entropy loss.", GOOD_CODE)
        assert 'PLUGIN_LOSS_TYPE = "ce"' in src
        assert "PLUGIN_LOSS_CONFIG_CLASS = CeConfig" in src
        assert "PLUGIN_LOSS_CLASS = Ce" in src

    def test_class_name_derived_from_loss_name(self):
        src = _assemble_loss_plugin("snr_weighted_mse", "x", GOOD_CODE)
        assert "class SnrWeightedMseConfig(BaseModel):" in src
        assert "class SnrWeightedMse(nn.Module):" in src
        assert 'PLUGIN_LOSS_TYPE = "snr_weighted_mse"' in src

    def test_forward_signature_is_fixed(self):
        """The forward signature is template-owned — the LLM cannot
        accidentally rename ``inputs`` / ``targets``."""
        src = _assemble_loss_plugin("ce", "x", GOOD_CODE)
        assert "def forward(self, inputs: torch.Tensor, targets: torch.Tensor)" in src

    def test_extra_imports_injected_above_template(self):
        code = dict(GOOD_CODE)
        code["extra_imports"] = "import math\nfrom typing import Optional"
        src = _assemble_loss_plugin("ce", "x", code)
        assert "import math" in src
        assert "from typing import Optional" in src

    def test_extra_imports_dedups_template_already_imported(self):
        """``import torch`` is in the template header; the LLM's restated
        ``import torch`` line must be silently dropped (matches the
        ``_assemble_plugin`` dedup behaviour for model plugins)."""
        code = dict(GOOD_CODE)
        code["extra_imports"] = "import torch\nimport math"
        src = _assemble_loss_plugin("ce", "x", code)
        # template's own `import torch` survives
        assert src.count("import torch\n") == 1
        # math (a new import) gets through
        assert "import math" in src

    def test_extra_imports_rejects_non_import_garbage(self):
        """LLMs sometimes emit partial fragments (e.g. ``torch.nn.functional
        as F``) into the imports slot. The assembly helper filters lines
        that are not real ``import``/``from ... import`` statements."""
        code = dict(GOOD_CODE)
        code["extra_imports"] = "torch.nn.functional as F  # bogus partial"
        src = _assemble_loss_plugin("ce", "x", code)
        # Bogus line must not appear in the assembled file.
        assert "torch.nn.functional as F  # bogus partial" not in src

    def test_empty_config_fields_falls_back_to_pass(self):
        """A loss with no tunable hyperparameters (LLM emits empty
        config_fields_code) must still produce a valid Config class body."""
        code = dict(GOOD_CODE)
        code["config_fields_code"] = ""
        code["config_fields"] = {}
        code["init_body"] = "        pass"
        src = _assemble_loss_plugin("ce", "x", code)
        # config body has a ``pass`` so the class body is not empty.
        assert "    pass" in src
        # And the assembled file still parses.
        import ast

        ast.parse(src)

    def test_indentation_normalised_from_llm_output(self):
        """The LLM can emit init_body with any indentation level (0/4/8
        spaces, or mixed). After assembly it must end up at 8 spaces
        (method-body level)."""
        code = dict(GOOD_CODE)
        code["init_body"] = "self.x = 1\nself.y = 2"  # zero-indent from LLM
        src = _assemble_loss_plugin("ce", "x", code)
        # Look for the canonical 8-space indented lines.
        assert "        self.x = 1" in src
        assert "        self.y = 2" in src

    def test_description_is_one_line_in_assembled_docstring(self):
        """Multi-line descriptions must collapse to one line so they fit
        in the class docstring without breaking it."""
        code = dict(GOOD_CODE)
        multiline = "First line.\nSecond line.\nThird line."
        src = _assemble_loss_plugin("ce", multiline, code)
        assert "First line. Second line. Third line." in src

    def test_description_double_quotes_escaped_to_single(self):
        """Double quotes in the description would terminate the triple-quoted
        docstring; the helper rewrites them as single quotes."""
        code = dict(GOOD_CODE)
        src = _assemble_loss_plugin("ce", 'A "quoted" word.', code)
        assert "A 'quoted' word." in src
        # No raw triple-double-quote in the description region.

    def test_missing_keys_substitute_safe_placeholders(self):
        """A code dict missing init_body / forward_body still assembles
        (with ``pass`` placeholders) so the downstream validator can return
        an informative error instead of crashing."""
        import ast

        # Only supply config_fields_code so the config class body isn't empty.
        code = {"config_fields_code": "    pass"}
        src = _assemble_loss_plugin("ce", "x", code)
        ast.parse(src)


# ---------------------------------------------------------------------------
# _dummy_tensor_validate_loss — post-assembly validation contract
# ---------------------------------------------------------------------------


class TestDummyTensorValidateLoss:
    def test_valid_loss_passes(self):
        """Cross-entropy on the canonical [B,256,T] / [B,T] contract must
        return None (no error)."""
        src = _assemble_loss_plugin("ce", "Cross-entropy.", GOOD_CODE)
        assert _dummy_tensor_validate_loss(src, "ce") is None

    def test_non_scalar_return_is_rejected(self):
        """If the LLM forgets to reduce the per-element loss to a scalar,
        the validator must catch it."""
        code = dict(GOOD_CODE)
        # F.cross_entropy with reduction='none' returns [B, T] instead of scalar.
        code["forward_body"] = "        return F.cross_entropy(inputs, targets, reduction='none')"
        src = _assemble_loss_plugin("ce_noreduce", "x", code)
        err = _dummy_tensor_validate_loss(src, "ce_noreduce")
        assert err is not None
        assert "SCALAR" in err

    def test_no_grad_block_is_rejected(self):
        """Wrapping the forward in torch.no_grad() detaches the graph; the
        validator must catch this via the requires_grad check."""
        code = dict(GOOD_CODE)
        code["forward_body"] = (
            "        with torch.no_grad():\n            return F.cross_entropy(inputs, targets)"
        )
        src = _assemble_loss_plugin("ce_nograd", "x", code)
        err = _dummy_tensor_validate_loss(src, "ce_nograd")
        assert err is not None
        assert "requires_grad" in err

    def test_nan_return_is_rejected(self):
        """A loss that returns NaN must be caught (final isfinite check)."""
        code = dict(GOOD_CODE)
        code["forward_body"] = (
            "        # Force NaN while preserving the autograd graph: 0/0\n"
            "        zero = inputs.sum() * 0.0\n"
            "        return zero / zero"
        )
        src = _assemble_loss_plugin("ce_nan", "x", code)
        err = _dummy_tensor_validate_loss(src, "ce_nan")
        assert err is not None
        assert "non-finite" in err

    def test_forward_raises_returns_error_string(self):
        """An exception in forward() must be caught and reported, not raised."""
        code = dict(GOOD_CODE)
        code["forward_body"] = "        raise RuntimeError('intentional test failure')"
        src = _assemble_loss_plugin("ce_raise", "x", code)
        err = _dummy_tensor_validate_loss(src, "ce_raise")
        assert err is not None
        assert "RuntimeError" in err
        assert "intentional test failure" in err

    def test_missing_required_attribute_returns_error_string(self):
        """A plugin file missing one of the 3 PLUGIN_LOSS_* constants is
        caught by the attribute presence check.

        We construct the broken source manually rather than via
        ``_assemble_loss_plugin`` (which is template-owned and always
        produces the constants)."""
        broken_src = (
            "import torch\n"
            "import torch.nn as nn\n"
            "from pydantic import BaseModel\n"
            "PLUGIN_LOSS_TYPE = 'broken'\n"
            "class BrokenConfig(BaseModel):\n"
            "    pass\n"
            "PLUGIN_LOSS_CONFIG_CLASS = BrokenConfig\n"
            "# Intentionally omit PLUGIN_LOSS_CLASS\n"
        )
        err = _dummy_tensor_validate_loss(broken_src, "broken")
        assert err is not None
        assert "PLUGIN_LOSS_CLASS" in err

    def test_config_default_failure_returns_error_string(self):
        """If PLUGIN_LOSS_CONFIG_CLASS() cannot be instantiated with no
        args (e.g. a required field with no default), the error string
        must mention the default requirement so the LLM can fix it."""
        code = dict(GOOD_CODE)
        # `Field(...)` with no default = required field.
        code["config_fields_code"] = "    required_param: float = Field(..., ge=0.0)"
        code["config_fields"] = {}
        code["init_body"] = "        self.required_param = config.required_param"
        src = _assemble_loss_plugin("ce_required", "x", code)
        err = _dummy_tensor_validate_loss(src, "ce_required")
        assert err is not None
        assert "default" in err.lower()


# ---------------------------------------------------------------------------
# Prompt constants — sanity that they are non-empty strings with the
# constraints L4 callers depend on.
# ---------------------------------------------------------------------------


class TestLossPrompts:
    def test_all_three_prompts_are_non_empty_strings(self):
        for name, prompt in [
            ("IMPLEMENTOR_LOSS_REASONING_PROMPT", IMPLEMENTOR_LOSS_REASONING_PROMPT),
            ("IMPLEMENTOR_LOSS_CODE_PROMPT", IMPLEMENTOR_LOSS_CODE_PROMPT),
            ("IMPLEMENTOR_LOSS_REPAIR_PROMPT", IMPLEMENTOR_LOSS_REPAIR_PROMPT),
        ]:
            assert isinstance(prompt, str), name
            assert prompt.strip(), f"{name} is empty"

    def test_reasoning_prompt_states_forward_contract(self):
        """The reasoning prompt must show the LLM the [B,256,T] / [B,T]
        forward contract — this is the single hardest constraint to
        recover from if missed."""
        assert "[B, num_classes, T]" in IMPLEMENTOR_LOSS_REASONING_PROMPT
        assert "[B, T]" in IMPLEMENTOR_LOSS_REASONING_PROMPT
        assert "requires_grad" in IMPLEMENTOR_LOSS_REASONING_PROMPT

    def test_code_prompt_states_signature_and_scalar_return(self):
        """The code-call prompt must name the fixed forward signature
        AND require a scalar return — the two most common LLM mistakes."""
        assert "forward(self, inputs: torch.Tensor, targets: torch.Tensor)" in (
            IMPLEMENTOR_LOSS_CODE_PROMPT
        )
        assert "SCALAR" in IMPLEMENTOR_LOSS_CODE_PROMPT

    def test_code_prompt_lists_six_json_fields(self):
        """The strict-JSON schema must list exactly the 6 fields the
        assembly helper consumes."""
        for field in (
            "extra_imports",
            "config_fields_code",
            "config_validators_code",
            "config_fields",
            "init_body",
            "forward_body",
        ):
            assert f'"{field}"' in IMPLEMENTOR_LOSS_CODE_PROMPT, field

    def test_repair_prompt_repeats_signature_anchor(self):
        """Repair prompt must remind the LLM of the forward signature so
        a wrong sig from attempt N doesn't survive into attempt N+1."""
        assert "forward(self, inputs, targets)" in IMPLEMENTOR_LOSS_REPAIR_PROMPT


# ---------------------------------------------------------------------------
# LOSS_PLUGIN_TEMPLATE — placeholder contract
# ---------------------------------------------------------------------------


class TestLossPluginTemplate:
    def test_template_has_all_named_placeholders(self):
        """Every named slot consumed by ``_assemble_loss_plugin`` must
        appear in the template — guards against renaming drift."""
        for placeholder in (
            "{loss_name}",
            "{LossClass}",
            "{description}",
            "{extra_imports}",
            "{config_fields_code}",
            "{config_validators_code}",
            "{init_body}",
            "{forward_body}",
        ):
            assert placeholder in LOSS_PLUGIN_TEMPLATE, placeholder

    def test_template_emits_three_required_plugin_loss_constants(self):
        """The 3 PLUGIN_LOSS_* constants are template-owned — they must
        appear in the raw template (before substitution)."""
        assert "PLUGIN_LOSS_TYPE = " in LOSS_PLUGIN_TEMPLATE
        assert "PLUGIN_LOSS_CONFIG_CLASS = " in LOSS_PLUGIN_TEMPLATE
        assert "PLUGIN_LOSS_CLASS = " in LOSS_PLUGIN_TEMPLATE
