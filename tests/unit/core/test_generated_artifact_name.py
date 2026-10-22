"""#778: generated identifiers must never become paths; valid identity is unchanged."""

import pytest

from core.generated_artifact_name import validate_generated_artifact_name


@pytest.mark.parametrize(
    "name",
    [
        None,
        1,
        "",
        ".",
        "..",
        "../escape",
        "/absolute",
        r"a\b",
        r"\\host\share",
        "C:drive",
        "a:b",
        "nul\0",
        "line\n",
        "tab\t",
        "del\x7f",
        "control\x85",
    ],
)
def test_refuses_path_and_control_components(name):
    with pytest.raises(ValueError, match="model_name must be"):
        validate_generated_artifact_name(name, field="model_name")


@pytest.mark.parametrize("name", ["Mixed_Case", "a-b", "v1.2", "模型", " spaced "])
def test_safe_identity_is_not_sanitized(name):
    assert validate_generated_artifact_name(name, field="model_name") == name
