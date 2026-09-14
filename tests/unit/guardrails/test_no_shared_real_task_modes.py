"""Keep scientific data and training qualification out of shared pytest modes.

The retired root options selected one TIDMAD file and one historical sandbox
while presenting themselves as framework-wide switches. A future task must own
its real data/executor qualification externally instead of restoring that
hidden default.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.conftest import _is_real_llm

ROOT = Path(__file__).resolve().parents[3]
RETIRED = ("--real" + "-data", "--real" + "-training", "_is_real" + "_training")
CURRENT_DOCS = (
    ROOT / "pyproject.toml",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "testing" / "ci_parity.md",
)


def _shared_mode_offenders(candidates: list[Path]) -> list[str]:
    offenders: list[str] = []
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        for token in RETIRED:
            if token in text:
                try:
                    display_path = path.relative_to(ROOT)
                except ValueError:
                    display_path = path
                offenders.append(f"{display_path}: {token}")
    return offenders


def test_live_test_surface_has_no_shared_real_task_mode() -> None:
    this_file = Path(__file__).resolve()
    candidates = [path for path in (ROOT / "tests").rglob("*.py") if path != this_file]
    candidates.extend((ROOT / "tests").rglob("*.md"))
    candidates.extend(CURRENT_DOCS)
    offenders = _shared_mode_offenders(candidates)
    assert not offenders, "shared task-specific real mode returned:\n" + "\n".join(offenders)


def test_guard_detects_a_reintroduced_shared_real_task_mode(tmp_path: Path) -> None:
    counterexample = tmp_path / "conftest.py"
    counterexample.write_text(
        f'parser.addoption("{RETIRED[1]}", action="store_true")\n',
        encoding="utf-8",
    )

    assert _shared_mode_offenders([counterexample]) == [f"{counterexample}: {RETIRED[1]}"]


def test_deprecated_api_alias_only_selects_the_real_llm_axis() -> None:
    def request(*, real_llm: bool, legacy_alias: bool) -> SimpleNamespace:
        values = {"--real-llm": real_llm, "--real-api-call": legacy_alias}
        return SimpleNamespace(config=SimpleNamespace(getoption=values.__getitem__))

    assert not _is_real_llm(request(real_llm=False, legacy_alias=False))
    assert _is_real_llm(request(real_llm=True, legacy_alias=False))
    assert _is_real_llm(request(real_llm=False, legacy_alias=True))
