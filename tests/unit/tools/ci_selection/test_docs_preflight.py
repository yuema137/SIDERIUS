"""The documentation fast path must never bless uncertain runtime changes."""

from pathlib import Path

import pytest

from tools.ci_selection.docs_preflight import is_ordinary_document, ordinary_docs_only


@pytest.fixture
def docs_root(tmp_path):
    (tmp_path / "README.md").write_text("# Example\n")
    folder = tmp_path / "docs/getting-started"
    folder.mkdir(parents=True)
    (folder / "first-run.md").write_text("# First run\n")
    return tmp_path


def test_audited_modifications_are_lightweight(docs_root):
    assert ordinary_docs_only(b"M\0README.md\0M\0docs/getting-started/first-run.md\0", docs_root)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"M\0README.md",
        b"M\0",
        b"M\0README.md\0extra\0",
        b"A\0README.md\0",
        b"D\0README.md\0",
        b"T\0README.md\0",
        b"R100\0README.md\0docs/getting-started/first-run.md\0",
        b"C100\0README.md\0docs/getting-started/first-run.md\0",
        b"M\0README.md\0M\0src/core/runtime.py\0",
        b"M\0docs/agent-reference/orchestrator-toolkit/payload/AGENTS.md\0",
        b"M\0src/agent/skills/example/SKILL.md\0",
        b"M\0docs/agent-reference/new-runtime-prompt.md\0",
        b"M\0../README.md\0",
        b"U\0README.md\0",
    ],
)
def test_unknown_or_non_modification_retains_normal_ci(docs_root, raw):
    assert not ordinary_docs_only(raw, docs_root)


def test_missing_files_and_symlinks_cannot_claim_documentation_only(docs_root):
    readme = docs_root / "README.md"
    readme.unlink()
    assert not ordinary_docs_only(b"M\0README.md\0", docs_root)
    readme.symlink_to(docs_root / "docs/getting-started/first-run.md")
    assert not ordinary_docs_only(b"M\0README.md\0", docs_root)


def test_runtime_steps_require_non_documentation_and_status_name_is_preserved():
    """The documentation fast path skips runtime work and keeps the status name.

    Fails as: a runtime step or unit-test job loses its docs-only gate (a docs PR
    pays for the full pipeline, or worse, a non-docs PR skips it), or the
    aggregate status reviewers read stops being "Lint + Type + Unit Tests" or
    stops depending on every lane.
    """
    import yaml

    root = Path(__file__).resolve().parents[4]
    jobs = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())["jobs"]
    quality = jobs["quality"]
    assert quality["name"] == "Lint + Type + Unit Tests"
    assert set(quality["needs"]) == {"prepare", "unit", "sensitive"}
    assert quality["if"] == "always()"

    steps = jobs["prepare"]["steps"]
    names = [step["name"] for step in steps]
    assert names.index("Classify ordinary documentation changes") < names.index(
        "Install dependencies (incl. dev group)"
    )
    for step in steps:
        run = step.get("run", "")
        if any(
            token in run
            for token in ("--group dev", "uv run ruff", "uv run pyright", "python -m tools.ci")
        ) or ("uses" in step and "upload-artifact" in step["uses"]):
            assert "steps.documentation.outputs.docs_only != 'true'" in step["if"]
    for lane in ("unit", "sensitive"):
        assert jobs[lane]["if"] == "needs.prepare.outputs.docs_only != 'true'"
    docs = next(step for step in steps if step["name"] == "Check ordinary documentation")
    assert "--only-group dev --frozen" in docs["run"]
    assert "--noconftest" in docs["run"]
    assert docs["if"] == "steps.documentation.outputs.docs_only == 'true'"


@pytest.mark.parametrize(
    "area", ["getting-started", "guides", "concepts", "reference", "releases", "audit"]
)
def test_audited_document_directories_have_a_generic_boundary(docs_root, area):
    name = f"docs/{area}/nested/example.md"
    path = docs_root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Documentation\n")
    assert ordinary_docs_only(f"M\0{name}\0".encode(), docs_root)


@pytest.mark.parametrize(
    "name",
    [
        "src/agent/prompt_templates/README.md",
        "docs/agent-reference/orchestrator-toolkit/payload/README.md",
        "docs/gates/gate_testing_standard.md",
        "docs/testing/ci_parity.md",
        "docs/design/proposal.md",
        "examples/example/README.md",
        "configs/README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/guides/example.py",
        "docs/guides-extra/example.md",
        "docs/guides/../../src/README.md",
        "docs//guides/example.md",
        "/docs/guides/example.md",
        "./README.md",
    ],
)
def test_nonordinary_or_noncanonical_paths_keep_normal_checks(name):
    assert not is_ordinary_document(name)
