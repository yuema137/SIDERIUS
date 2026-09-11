"""F-SCANB-4 — auto-resume START_ITER capture validation (wave3 repair R3).

``run_chain.sh``'s auto-resume captured ``scripts/inspect_run_state.py
--next-iter`` stdout into ``START_ITER`` with NO validation, and that capture
can carry import-time plugin-loader chatter (observed ~12,960 bytes) ahead of
the value — so resume broke exactly when it mattered, with ``--start_iter N``
as the known workaround. The repair adds
``extract_validated_next_iter`` (``_chain_common.sh``): the exit-0 capture's
LAST line is the value channel (the inspector prints the integer as its final
stdout write; every diagnostic goes to stderr), accepted only as a bare
non-negative integer; anything else makes ``resolve_start_iter`` REFUSE
loudly, naming the workaround — never a silent default, because a wrong
iteration index corrupts a resumed campaign.

The behavioural tests drive the REAL shell function by sourcing
``_chain_common.sh`` (safe: its top level is ``set -e`` + plain default
assignments); the wiring tests pin, at the text level (the
``test_chain_consistency.py`` convention), that ``resolve_start_iter``
actually routes the capture through the validator and that the refusal names
the workaround — so the guard cannot silently fall out of the production
path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAIN_COMMON = REPO_ROOT / "scripts" / "launch" / "_chain_common.sh"
RUN_CHAIN = REPO_ROOT / "scripts" / "launch" / "run_chain.sh"

#: Realistic pollution: the plugin loader prints per-plugin lines on import.
_PLUGIN_CHATTER = "\n".join(
    f"[plugin_loader] registered agent_generated/models/model_{i:04d}.py" for i in range(200)
)


def _extract(raw: str) -> subprocess.CompletedProcess:
    """Run the real ``extract_validated_next_iter`` on ``raw``."""
    return subprocess.run(
        [
            "bash",
            "-c",
            f'source "{CHAIN_COMMON}"; extract_validated_next_iter "$1"',
            "_",
            raw,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


class TestExtractValidatedNextIter:
    """The value channel: last line of an exit-0 capture, integers only."""

    def test_clean_capture_passes_through(self):
        """The pre-existing healthy case is byte-preserved: a bare integer
        capture (inspector with a quiet import) validates to itself."""
        res = _extract("3")
        assert res.returncode == 0
        assert res.stdout == "3\n"

    def test_plugin_chatter_prefix_is_survived(self):
        """THE F-SCANB-4 operational fix. Pre-fix the whole polluted capture
        was assigned to START_ITER and the resume broke; the value is the
        inspector's final stdout line, so a chatter-prefixed capture now
        resolves to the integer. Fails when: the helper stops isolating the
        last line (resume under plugin chatter breaks again)."""
        assert len(_PLUGIN_CHATTER) > 10_000  # same order as the observed 12,960B
        res = _extract(_PLUGIN_CHATTER + "\n7")
        assert res.returncode == 0
        assert res.stdout == "7\n"

    @pytest.mark.parametrize(
        ("raw", "why"),
        [
            pytest.param("", "empty capture", id="empty"),
            pytest.param("no integer anywhere", "no value at all", id="prose"),
            pytest.param(
                "5\ntrailing chatter", "integer is not the LAST line", id="value_then_chatter"
            ),
            pytest.param("-1", "negative index", id="negative"),
            pytest.param("3.5", "non-integer numeric", id="float"),
            pytest.param("3 ", "trailing whitespace — not a bare integer", id="trailing_space"),
            pytest.param(
                "chatter without newline3",
                "chatter glued to the value (unterminated line) is ambiguous",
                id="glued",
            ),
        ],
    )
    def test_anything_else_refuses_instead_of_guessing(self, raw: str, why: str):
        """Never a silent default: a capture whose last line is not a bare
        non-negative integer returns 1 and prints nothing, so the caller's
        loud refusal (naming --start_iter N) is the ONLY outcome. Fails
        when: the helper starts guessing (e.g. grepping any digit run) or
        defaulting — the silent-iteration-corruption failure mode."""
        res = _extract(raw)
        assert res.returncode == 1, why
        assert res.stdout == ""


class TestResolveStartIterWiring:
    """The production path routes through the validator and refuses loudly.

    Text-level pins in the ``test_chain_consistency.py`` convention: these
    fail when the capture is assigned to START_ITER without the validator
    again, or when the refusal stops naming the operator workaround.
    """

    def test_the_capture_is_routed_through_the_validator(self):
        text = RUN_CHAIN.read_text(encoding="utf-8")
        assert 'START_ITER=$(extract_validated_next_iter "$_raw_next_iter")' in text, (
            "resolve_start_iter no longer validates the inspector capture — "
            "F-SCANB-4 regressed: a chatter-polluted stdout would be "
            "assigned to START_ITER verbatim"
        )

    def test_no_unvalidated_direct_capture_remains(self):
        """The pre-fix shape — assigning the inspector's stdout directly to
        START_ITER — must not reappear beside the validated path."""
        text = RUN_CHAIN.read_text(encoding="utf-8")
        assert "START_ITER=$(" + '"${PY_CMD[@]}"' not in text.replace(" \\\n", " ")

    def test_the_refusal_names_the_workaround(self):
        text = RUN_CHAIN.read_text(encoding="utf-8")
        assert "Workaround: pass --start_iter N explicitly" in text, (
            "the refusal must hand the operator the known workaround "
            "(--start_iter N) — a bare failure strands a resumed campaign"
        )

    def test_both_scripts_still_parse(self):
        for script in (RUN_CHAIN, CHAIN_COMMON):
            res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            assert res.returncode == 0, f"bash -n failed for {script}:\n{res.stderr}"
