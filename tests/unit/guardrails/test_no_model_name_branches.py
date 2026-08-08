"""Phase 6.6 §5.4 — mechanical enforcement of Principle 2 (no model-name branches).

Greps the VRAM/training/inference estimation surface for literal architecture
names (``wavenet``, ``punet``, ``fcnet``, ``rnn``, ``transformer``, ``cnn``,
case-insensitive). Any occurrence in live code is a failure of the phase — the
estimation vocabulary is supposed to be generic (*tensor, channel dimension,
split, gated activation, attention head*), not family-specific.

Allowed places the token may appear:
  * Inside docstrings that explicitly annotate the match as an example (the
    token is preceded by ``e.g.`` or ``example``).
  * Inside a triple-backtick fenced code block rendering a file-format sample
    (JSON, YAML, config) where the value is documentation, not logic.

Everywhere else — ``if model_type == "fcnet":``, dict keys, default values —
is a Principle 2 violation.

Scope (§5.4): ``agent/skills/evaluate_vram_skill/``,
``agent/skills/training_skill/estimator.py``,
``agent/skills/inference_skill/estimator.py``, ``core/inference_defaults.py``.

Scope expansion: as A.6 (training_skill/estimator.py rewrite), A.7
(inference_skill/estimator.py rewrite), and A.9 (delete inference_defaults.py)
land, the corresponding files become clean. Until then, those files are
excluded from the live-code scan via ``xfail`` to keep the guardrail useful
for the already-clean ``evaluate_vram_skill/`` surface without blocking on
out-of-pass work.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Case-insensitive token pattern. ``\b`` word boundaries so substrings like
# ``unchannelised`` don't trip ``cnn``.
_MODEL_NAME_PATTERN = re.compile(
    r"\b(wavenet|punet|fcnet|rnn|transformer|cnn)\b",
    re.IGNORECASE,
)

# Files / dirs to scan — pinned by §5.4.
_SCAN_TARGETS: list[tuple[str, str]] = [
    # (label, path — may be a file or a directory)
    ("evaluate_vram_skill", "agent/skills/evaluate_vram_skill"),
    ("training_estimator", "agent/skills/training_skill/estimator.py"),
    ("inference_estimator", "agent/skills/inference_skill/estimator.py"),
    ("inference_defaults", "core/inference_defaults.py"),
]

# Known-dirty targets pending their unblocking refactor. Each entry documents
# *which* phase step will clean the file — when that step lands, drop the
# entry here. The test still scans them and prints any violations as xfail
# output so a regression (new violation in a file we thought we'd only
# shrink) is still visible.
#
# V21 PR C3 — EMPTIED. All three entries were removed once their groups came
# clean, and emptying it is the point rather than a tidy-up: while a label sat
# here, a REINTRODUCED name branch was reported as ``xfail`` instead of
# ``failed``, so the guard detected the regression and then tolerated it.
# Verified by mutation: re-adding ``if model_type == "transformer":`` produced
# "3 passed, 1 xfailed" with the entry present, and a hard failure without it.
#
# The three reasons here were also stale in the way the operator flagged
# during PR A's merge — they named an "A.6 / A.7 / A.9" plan that V21
# superseded, pointing a future reader at work nobody was going to do.
#
# Re-add an entry only for a group that is genuinely dirty and genuinely
# blocked, and name the CURRENT owning PR.
_PENDING_CLEANUP: dict[str, str] = {}


def _is_allowed_example(line: str) -> bool:
    """Return True if a line carrying the token is an explicitly-marked
    example, not live code. Intentionally strict: the line must contain an
    ``e.g.`` or ``example`` marker or be inside an indented fenced code block
    (heuristic: starts with ``|`` or `"` and the token is inside quotes with
    key-like whitespace). Ambiguous cases fail closed."""
    stripped = line.strip()
    # Docstring/comment with an "e.g."/"example" annotation in the same line.
    if ("e.g." in stripped.lower()) or ("example" in stripped.lower()):
        return True
    # JSON/YAML sample inside a docstring: `"gpu_name":  "NVIDIA ..."` style
    # — dict-literal-in-docs where the token is the *value* of a documented
    # field. Heuristic: the line contains a quoted key-value pair with a
    # leading quote (or whitespace-indented quote).
    if re.match(r'^\s*"[\w]+"\s*:\s*', stripped):
        return True
    # Fenced code block line inside a docstring (handled by the block-scan
    # path, not per-line). Err on the side of caller: return False here and
    # let the block scanner above make the call.
    return False


def _code_only_lines(text: str) -> list[str]:
    """Return the file's lines with ``#`` comment text blanked out.

    V21 PR C3. The guard exists to catch model-name branching in **live
    code**; a comment cannot branch on anything. Before this, ``#`` comments
    were scanned like code while docstrings were exempt, which is an
    inconsistency that cost real accuracy in both directions:

      * false positives — the pre-existing calibration note
        "calibrated on seed models (punet, wavenet)" counted as a
        violation, so the tracked "9 violations" were never 9 code
        branches, and the only way to reach zero was to delete truthful
        documentation;
      * a perverse incentive — the cheapest way to clear the guard was to
        stop *explaining* which model a formula came from.

    Only the comment token's text is removed, never the code preceding it,
    so ``foo("transformer")  # note`` is still a violation. Docstrings
    continue to be handled by the caller's existing block scan.

    Falls back to the raw lines if the file does not tokenize (syntax error
    mid-edit): failing loud is better than silently scanning nothing.
    """
    import io
    import tokenize

    lines = text.splitlines()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return lines

    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        row = tok.start[0] - 1
        if 0 <= row < len(lines):
            # Keep everything before the ``#`` so trailing comments do not
            # exempt the code on the same line.
            lines[row] = lines[row][: tok.start[1]]
    return lines


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return ``[(lineno, line_text), ...]`` for every violation in the file.

    A line is a violation when:
      * its **code** contains at least one model-name token (``#`` comment
        text is stripped first — see :func:`_code_only_lines`), AND
      * it is not inside a fenced code block that itself is inside a
        triple-quoted docstring (which we treat as documentation), AND
      * it is not marked as an explicit example on the line itself.
    """
    text = path.read_text()
    lines = _code_only_lines(text)

    # Pass 1 — find docstring / fenced-code regions to exclude.
    in_fenced_block = False
    in_docstring = False
    docstring_delim = None
    allowed_line_numbers: set[int] = set()

    for idx, line in enumerate(lines, start=1):
        if in_docstring:
            if docstring_delim in line:
                in_docstring = False
                docstring_delim = None
            allowed_line_numbers.add(idx)
            if "```" in line:
                in_fenced_block = not in_fenced_block
            continue
        stripped = line.strip()
        if stripped.startswith(('"""', "'''")):
            delim = stripped[:3]
            # single-line docstring: "text text text"
            rest = stripped[3:]
            if delim in rest:
                allowed_line_numbers.add(idx)
                continue
            in_docstring = True
            docstring_delim = delim
            allowed_line_numbers.add(idx)
            continue

    # Pass 2 — flag violations on any line that contains the token and is
    # NOT in the allowed set, unless the line itself carries an inline
    # example marker.
    violations: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        if not _MODEL_NAME_PATTERN.search(line):
            continue
        if idx in allowed_line_numbers:
            continue
        # Single-line ``#`` comments whose text is annotated "e.g." also ok.
        if _is_allowed_example(line):
            continue
        violations.append((idx, line.rstrip()))

    return violations


def _iter_target_files(target_path: str):
    root = _REPO_ROOT / target_path
    if not root.exists():
        # File deleted by a later phase (e.g. A.9 removes inference_defaults):
        # not a violation — there is nothing to scan. Emit no paths.
        return
    if root.is_file() and root.suffix == ".py":
        yield root
        return
    if root.is_dir():
        for p in sorted(root.rglob("*.py")):
            if p.name == "__init__.py" and p.stat().st_size == 0:
                continue
            yield p


@pytest.mark.parametrize("label,target_path", _SCAN_TARGETS, ids=[t[0] for t in _SCAN_TARGETS])
def test_no_model_name_branches(label: str, target_path: str) -> None:
    """Per-target parametrisation: one test case per scanned file/dir.

    This lets the already-clean ``evaluate_vram_skill`` target enforce
    cleanliness immediately while the as-yet-unrewritten estimators stay
    as xfail until their phase lands."""
    all_violations: list[str] = []
    for path in _iter_target_files(target_path):
        rel = path.relative_to(_REPO_ROOT)
        for lineno, text in _scan_file(path):
            all_violations.append(f"{rel}:{lineno}:{text}")

    if label in _PENDING_CLEANUP and all_violations:
        pytest.xfail(
            f"{label}: {len(all_violations)} model-name violation(s) pending — "
            f"{_PENDING_CLEANUP[label]}. First match: {all_violations[0]}"
        )

    assert not all_violations, (
        f"[{label}] Principle 2 violations — model-name branching in live code:\n"
        + "\n".join(all_violations)
        + "\n\nMove to a generic predicate (introspection, metadata flag, "
        "contract-level dispatch). Do not re-introduce model-family strings."
    )
