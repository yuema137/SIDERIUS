"""
Tests for agent/schemas/validator.py

Parametrized to keep the defensive Pydantic shield intact (required-field
ValidationError pins) while collapsing one-input-per-function noise into
single parametrized functions with explicit case IDs.
"""
import pytest
from pydantic import ValidationError

from agent.schemas.validator import ValidatorInput, ValidatorOutput, LLMCodeReview


VALID_INPUT_KWARGS = dict(
    model_type="attn_unet",
    model_file_path="/abs/agent_generated/models/attn_unet.py",
    test_file_path="/abs/agent_generated/tests/test_attn_unet.py",
    description_file_path="/abs/agent_generated/models/attn_unet/description.md",
    config_fields={"depth": 2, "channels": 64},
    model_description="A U-Net variant with multi-head self-attention at the bottleneck.",
    mathematical_definition="1. Embedding: nn.Embedding(256, 32). 2. Encoder: 3 down-blocks.",
)

REQUIRED_INPUT_FIELDS = [
    "model_type",
    "model_file_path",
    "description_file_path",
    "config_fields",
    "model_description",
    "mathematical_definition",
]

REQUIRED_OUTPUT_FIELDS = [
    "model_type",
    "tests_passed",
    "instantiation_passed",
    "gradient_check_passed",
    "llm_review_passed",
]


def _valid_output_kwargs(**overrides):
    base = dict(
        passed=True,
        model_type="attn_unet",
        plugin_registered=True,
        tests_passed=True,
        description_valid=True,
        config_fields_valid=True,
        instantiation_passed=True,
        gradient_check_passed=True,
        llm_review_passed=True,
    )
    base.update(overrides)
    return base


class TestValidatorInput:

    def test_valid_construction_populates_all_documented_fields(self):
        """Sanity baseline: every kwarg lands on the model, plus default
        storage/LLM settings resolve as advertised."""
        inp = ValidatorInput(**VALID_INPUT_KWARGS)
        assert inp.model_type == "attn_unet"
        assert inp.description_file_path.endswith("description.md")
        assert inp.config_fields == {"depth": 2, "channels": 64}
        assert "U-Net" in inp.model_description
        assert "Embedding" in inp.mathematical_definition
        assert inp.storage.backend == "local"
        assert inp.llm_provider == "gemini"
        assert inp.llm_model_id == "gemini-3.1-flash-lite-preview"

    def test_custom_llm_provider_overrides_default(self):
        inp = ValidatorInput(**VALID_INPUT_KWARGS, llm_provider="openai")
        assert inp.llm_provider == "openai"

    def test_storage_custom_overrides_default(self):
        inp = ValidatorInput(
            **VALID_INPUT_KWARGS,
            storage={"backend": "local", "local": {"workspace": "/reports", "run_name": "r1"}},
        )
        assert inp.storage.local.workspace == "/reports"

    @pytest.mark.parametrize("missing_field", REQUIRED_INPUT_FIELDS)
    def test_missing_required_field_raises(self, missing_field):
        """Defensive shield: dropping any required field must surface as a
        ValidationError naming the field. Keeps schema regressions loud
        even though Pydantic enforces this internally."""
        kwargs = {k: v for k, v in VALID_INPUT_KWARGS.items() if k != missing_field}
        with pytest.raises(ValidationError) as exc:
            ValidatorInput(**kwargs)
        assert missing_field in str(exc.value)


class TestValidatorOutput:

    @pytest.mark.parametrize(
        "case_overrides, key_field, key_value",
        [
            pytest.param(
                {},
                "passed", True,
                id="all_passed_no_test_output",
            ),
            pytest.param(
                {"test_output": "3 passed in 0.5s"},
                "test_output", "3 passed in 0.5s",
                id="all_passed_with_test_output",
            ),
        ],
    )
    def test_passed_scenarios_construct_and_expose_optional_fields(
        self, case_overrides, key_field, key_value,
    ):
        out = ValidatorOutput(**_valid_output_kwargs(**case_overrides))
        assert getattr(out, key_field) == key_value
        # When no test_output supplied, both optional fields stay None.
        if not case_overrides:
            assert out.error_message is None
            assert out.test_output is None

    @pytest.mark.parametrize(
        "overrides, expected_field, expected_value, side_check",
        [
            pytest.param(
                {
                    "passed": False, "plugin_registered": False, "tests_passed": False,
                    "instantiation_passed": False, "gradient_check_passed": False,
                    "llm_review_passed": False,
                    "error_message": "ImportError: cannot import PLUGIN_MODEL_CLASS",
                },
                "passed", False,
                ("error_message", "ImportError"),
                id="failed_plugin_import",
            ),
            pytest.param(
                {
                    "passed": False, "tests_passed": False,
                    "test_output": "FAILED test_forward_shape - AssertionError",
                    "error_message": "1 test failed",
                },
                "tests_passed", False,
                ("test_output", "FAILED"),
                id="failed_pytest",
            ),
            pytest.param(
                {
                    "passed": False, "config_fields_valid": False,
                    "error_message": "config field 'kernel_sizes' is List[int], not scalar",
                },
                "config_fields_valid", False,
                None,
                id="failed_config_fields",
            ),
            pytest.param(
                {
                    "passed": False, "instantiation_passed": False,
                    "gradient_check_passed": False,
                    "error_message": "Model instantiation failed",
                },
                "instantiation_passed", False,
                ("gradient_check_passed", False),
                id="failed_instantiation",
            ),
            pytest.param(
                {
                    "passed": False, "gradient_check_passed": False,
                    "error_message": "Backward pass failed",
                },
                "gradient_check_passed", False,
                ("instantiation_passed", True),
                id="failed_gradient_only",
            ),
            pytest.param(
                {
                    "passed": False, "llm_review_passed": False,
                    "llm_review_spec_alignment": False,
                    "llm_review_trainability_concerns": ["detached tensor in residual"],
                    "llm_review_implementation_issues": [],
                    "llm_review_notes": "Implementation does not match spec.",
                    "error_message": "LLM review did not pass",
                },
                "llm_review_passed", False,
                ("llm_review_spec_alignment", False),
                id="failed_llm_review",
            ),
        ],
    )
    def test_failure_scenarios_preserve_per_stage_flags(
        self, overrides, expected_field, expected_value, side_check,
    ):
        """Each documented failure shape must round-trip through Pydantic
        and surface the right stage flag (plus a documented side-channel
        field like error_message / test_output / a sibling stage flag)."""
        out = ValidatorOutput(**_valid_output_kwargs(**overrides))
        assert getattr(out, expected_field) == expected_value
        if side_check is not None:
            side_name, side_expected = side_check
            actual = getattr(out, side_name)
            if isinstance(side_expected, str):
                assert side_expected in actual
            else:
                assert actual == side_expected

    def test_failed_llm_review_records_concerns_list(self):
        """Multi-field assertion broken out because the trainability_concerns
        length check is a distinct invariant (list cardinality)."""
        out = ValidatorOutput(**_valid_output_kwargs(
            passed=False,
            llm_review_passed=False,
            llm_review_spec_alignment=False,
            llm_review_trainability_concerns=["detached tensor in residual"],
            llm_review_implementation_issues=[],
            llm_review_notes="Implementation does not match spec.",
            error_message="LLM review did not pass",
        ))
        assert len(out.llm_review_trainability_concerns) == 1

    @pytest.mark.parametrize("missing_field", REQUIRED_OUTPUT_FIELDS)
    def test_missing_required_field_raises(self, missing_field):
        """Defensive shield (mirrors TestValidatorInput): dropping any
        required ValidatorOutput field must surface as a named ValidationError."""
        kwargs = _valid_output_kwargs()
        kwargs.pop(missing_field)
        with pytest.raises(ValidationError) as exc:
            ValidatorOutput(**kwargs)
        assert missing_field in str(exc.value)


class TestLLMCodeReview:

    @pytest.mark.parametrize(
        "kwargs, expected_passed, expected_concerns_len, expected_issues_len",
        [
            pytest.param(
                dict(
                    spec_alignment=True,
                    trainability_concerns=[],
                    implementation_issues=[],
                    passed=True,
                    notes="Implementation looks correct.",
                ),
                True, 0, 0,
                id="passed",
            ),
            pytest.param(
                dict(
                    spec_alignment=False,
                    trainability_concerns=["detached tensor"],
                    implementation_issues=["wrong shape"],
                    passed=False,
                    notes="Does not match spec.",
                ),
                False, 1, 1,
                id="failed",
            ),
        ],
    )
    def test_review_scenarios(
        self, kwargs, expected_passed, expected_concerns_len, expected_issues_len,
    ):
        review = LLMCodeReview(**kwargs)
        assert review.passed is expected_passed
        assert review.spec_alignment is kwargs["spec_alignment"]
        assert len(review.trainability_concerns) == expected_concerns_len
        assert len(review.implementation_issues) == expected_issues_len
