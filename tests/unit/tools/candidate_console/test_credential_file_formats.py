"""`credential_file` accepts JSON or dotenv text and never exposes values.

Only fake values are written, always inside ``tmp_path``.
"""

import logging

import pytest

from tools.candidate_console.files import credentials
from tools.candidate_operations.models import OperationFailure

FAKE = "fake-secret-value-7f3a"

DOTENV = f"""\
# operator comment, OPENAI_API_KEY=not-this-one
export OPENAI_API_KEY={FAKE}-openai
GEMINI_API_KEY='{FAKE}-single quoted'
DEEPSEEK_API_KEY="{{{FAKE}}}"
UNDECLARED_NAME={FAKE}-undeclared
INTERPOLATED=${{HOME}}-{FAKE}
NAME_WITHOUT_VALUE
"""


def _private(tmp_path, text: str, mode: int = 0o600) -> str:
    path = tmp_path / "keys.env"
    path.write_text(text)
    path.chmod(mode)
    return str(path)


def test_dotenv_file_yields_only_declared_names(tmp_path):
    """Fails if dotenv text is refused, misparsed, interpolated or leaks undeclared names.

    The ``DEEPSEEK_API_KEY`` value starts with ``{``; detection keys on the
    file's first non-whitespace byte, so it must stay dotenv.
    """
    path = _private(tmp_path, DOTENV)
    declared = ("OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "INTERPOLATED")
    assert credentials(path, declared) == {
        "OPENAI_API_KEY": f"{FAKE}-openai",
        "GEMINI_API_KEY": f"{FAKE}-single quoted",
        "DEEPSEEK_API_KEY": "{" + FAKE + "}",
        "INTERPOLATED": "${HOME}-" + FAKE,
    }


def test_leading_whitespace_json_still_uses_strict_json(tmp_path):
    """Fails if JSON detection ignores leading whitespace or loosens JSON typing."""
    path = _private(tmp_path, f'\n  {{"OPENAI_API_KEY": "{FAKE}"}}')
    assert credentials(path, ("OPENAI_API_KEY",)) == {"OPENAI_API_KEY": FAKE}
    path = _private(tmp_path, '{"OPENAI_API_KEY": 7}')
    with pytest.raises(OperationFailure):
        credentials(path, ("OPENAI_API_KEY",))


@pytest.mark.parametrize(
    ("text", "mode", "names"),
    [
        (f"OPENAI_API_KEY={FAKE}\n", 0o644, ("OPENAI_API_KEY",)),
        (
            f"OPENAI_API_KEY={FAKE}\nNAME_WITHOUT_VALUE\n",
            0o600,
            ("GEMINI_API_KEY", "NAME_WITHOUT_VALUE"),
        ),
        (f'{{"OPENAI_API_KEY": "{FAKE}", broken', 0o600, ("OPENAI_API_KEY",)),
        (f'{{"OPENAI_API_KEY": ["{FAKE}"]}}', 0o600, ("OPENAI_API_KEY",)),
        (f"OPENAI_API_KEY={FAKE}\udcff\n", 0o600, ("OPENAI_API_KEY",)),
    ],
    ids=["mode-0644", "missing-names", "malformed-json", "non-string-json", "non-utf8-dotenv"],
)
def test_refusals_carry_names_only(tmp_path, caplog, text, mode, names):
    """Fails if a refusal, its chained cause or a log record quotes a credential value."""
    path = tmp_path / "keys.env"
    path.write_bytes(text.encode("utf-8", "surrogateescape"))
    path.chmod(mode)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(OperationFailure) as refused:
        credentials(str(path), names)
    chain = []
    error: BaseException | None = refused.value
    while error is not None:
        chain.append(str(error))
        error = error.__cause__ or error.__context__
    assert FAKE not in " ".join(chain) + caplog.text
    if mode == 0o600 and "NAME_WITHOUT_VALUE" in names:
        assert str(refused.value) == "missing credentials: GEMINI_API_KEY, NAME_WITHOUT_VALUE"


def test_startup_check_accepts_dotenv_and_refuses_open_mode(console_config, tmp_path):
    """Fails if `validate_config` keeps a JSON-only shape check or skips permissions."""
    from tools.candidate_console.config import validate_config

    path = tmp_path / "creds" / ".env"
    path.parent.mkdir()
    path.write_text(DOTENV)
    path.chmod(0o600)
    config = console_config.model_copy(update={"credential_file": str(path)})
    assert validate_config(config).credential_file == str(path)
    path.chmod(0o644)
    with pytest.raises(OperationFailure):
        validate_config(config)
