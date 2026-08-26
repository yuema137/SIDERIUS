"""arXiv U3 (#260) — the isolated prompt census over a one-iteration pseudo chain.

The acceptance criterion, literally: under ``--baseline_isolation`` the
run's ACTUAL prompt surface — every prompt the real interpreter and real
proposer render, plus the persisted proposing-stage prompt — contains no
bundled architecture name, no bundled ``description.md`` header, no
baseline SOTA figure (``5.57``) and no FCNet-scale literal (``323``).

Mechanism: the REAL interpreter (cold start — its deterministic no-LLM
path) and the REAL proposer run under a capturing ``StubLLMBridge``
subclass (the PR-12a harness: production render paths, recorded bytes, no
API), with the implementor / validator / tuner mocked — their prompt
surfaces are not U3's (the tuner's planner templates are 12d-active and
carry a KNOWN, separately-pinned built-in roster).

Non-vacuity: the SAME drive without isolation must contain ``wavenet``
and ``5.57`` — a census green on both arms would be measuring nothing.

Environmental note: the proposer renders the live capability index
(``agent_generated/_capability_index.json``). On a machine whose index
carries a plugin whose description names a bundled architecture, this
census goes RED — correctly: that text would reach the isolated prompt.

Pseudo only: no LLM call, no GPU, no training subprocess.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.helpers.step12_pr12a_prompt_capture import capturing_bridge_class
from tests.integration.workflows.test_chain_candidate_graduation import _llm_config_pseudo
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_tuning_output,
    _make_validator_output,
)
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig

BUNDLED_NAMES = ("punet", "fcnet", "transformer", "wavenet", "rnn", "gated_fno")
_BUNDLED_RE = re.compile(r"\b(" + "|".join(BUNDLED_NAMES) + r")\b", re.IGNORECASE)

#: First heading line of each bundled ml_models/*/description.md.
BUNDLED_DESCRIPTION_HEADERS = (
    "FCNet — Fully Connected AutoEncoder",
    "GatedFNO — Full-Spectrum Gated Fourier Neural Operator",
    "PUNet — Positional U-Net",
    "RNN — LSTM Encoder-Decoder (Seq2Seq)",
    "Transformer — Transformer Encoder",
    "WaveNet — Dilated Causal WaveNet",
)


def _drive(workspace: str, *, isolation: bool) -> tuple[list[dict], Path]:
    bridges: list = []
    bridge_cls = capturing_bridge_class()

    def bridge_factory(**kwargs):
        bridge = bridge_cls(**kwargs)
        bridges.append(bridge)
        return bridge

    with (
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        MockImpl.return_value.run.side_effect = lambda inp: _make_implementor_output(
            model_type=inp.model_name
        )
        MockValid.return_value.run.side_effect = lambda inp: _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = lambda inp: _make_tuning_output(
            model_type=inp.model_type
        )
        run_workflow(
            launch=WorkflowLaunchConfig(
                source_paths=[],
                max_iterations=1,
                start_iteration=1,
                baseline_isolation=isolation,
                experiment_arm="without-prior-art" if isolation else None,
                debug_dump_prompts=True,
                is_trial=True,
            ),
            workspace=workspace,
            run_name="census",
            llm_config=_llm_config_pseudo(),
            bridge_factory=bridge_factory,
        )
    captures = [c for b in bridges for c in b.captures]
    dump = Path(workspace) / "census" / "debug"
    return captures, dump


#: The static feature vocabulary renders CODE-DETECTION regexes like
#: ``[pattern: MultiheadAttention|TransformerEncoder|transformer]`` — torch
#: symbol matchers for a MECHANISM (self-attention), not references to the
#: shipped ``transformer`` baseline. Those spans are excluded from the
#: bundled-name census; the same word ANYWHERE ELSE still fails it.
_VOCAB_PATTERN_SPAN = re.compile(r"\[pattern:[^\]]*\]")


def _census(text: str, *, where: str) -> list[str]:
    problems = []
    text = _VOCAB_PATTERN_SPAN.sub("[pattern: <mechanism-detector>]", text)
    hit = _BUNDLED_RE.search(text)
    if hit:
        problems.append(f"{where}: bundled architecture name {hit.group(0)!r}")
    for header in BUNDLED_DESCRIPTION_HEADERS:
        if header in text:
            problems.append(f"{where}: bundled description header {header!r}")
    if "5.57" in text:
        problems.append(f"{where}: baseline SOTA figure 5.57")
    if re.search(r"\b323\b", text):
        problems.append(f"{where}: FCNet-scale literal 323")
    return problems


@pytest.mark.dual_mode
def test_isolated_chain_prompts_carry_no_baseline_literal(tmp_path):
    ws = str(tmp_path / "isolated")
    os.makedirs(ws)
    captures, dump_dir = _drive(ws, isolation=True)
    assert captures, "the pseudo chain rendered no prompt — the census is vacuous"

    problems: list[str] = []
    for i, cap in enumerate(captures):
        where = f"capture[{i}] label={cap.get('label')} method={cap.get('method')}"
        problems += _census(cap.get("system", ""), where=where + " system")
        problems += _census(cap.get("user", ""), where=where + " user")

    dumped = sorted(dump_dir.glob("*proposing_system_prompt.md"))
    assert dumped, f"no persisted proposing prompt under {dump_dir}"
    for path in dumped:
        problems += _census(path.read_text(encoding="utf-8"), where=f"persisted {path.name}")

    assert not problems, "isolated prompt surface leaked baseline literals:\n" + "\n".join(problems)


@pytest.mark.dual_mode
def test_the_census_is_not_vacuous_the_legacy_surface_does_name_the_baseline(tmp_path):
    """Same drive, isolation OFF: the stage examples name wavenet / 5.57.
    If this stops being true the census above could go green by measuring
    nothing — this is the counterfactual that keeps it honest."""
    ws = str(tmp_path / "legacy")
    os.makedirs(ws)
    captures, _ = _drive(ws, isolation=False)
    joined = "\n".join(c.get("system", "") + "\n" + c.get("user", "") for c in captures)
    assert re.search(r"\bwavenet\b", joined, re.IGNORECASE)
    assert "5.57" in joined
