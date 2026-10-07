"""arXiv U3 (#260, ruling R6) — the proposer prompt surface under isolation.

The worked examples in ``comparison_stage.md`` / ``causal_reasoning_stage.md``
and the model-registry block used to hardcode the shipped WaveNet baseline
and its 5.57 score. They are tokens now; what only these tests catch:

* ``TestLegacyRenderIsByteIdentical`` — the NON-isolated render reproduces
  the pre-U3 template bytes EXACTLY, pinned by the sha256 each file had at
  the base SHA ``c991d6f6`` (hardcoded — never recomputed from the tree).
  Fails when the tokenization drifts a byte of any legacy prompt, which no
  behavioural test can see.
* ``TestIsolatedRenderNamesNoBaseline`` — the isolated render of every
  stage/mode and of the registry block contains no bundled architecture
  name, no ``5.57``, no FCNet-scale ``323`` and no unsubstituted example
  token. Fails when a baseline literal is reintroduced into a template.
* ``TestExampleLiteralAuthorities`` — the isolated literal set itself is
  neutral; hardcoded, so the authority cannot drift silently.
"""

from __future__ import annotations

import hashlib
import re
from unittest.mock import patch

from agent.prompt_templates.proposal import (
    _MODEL_REGISTRY_EMPTY_FALLBACK,
    _MODEL_REGISTRY_EMPTY_FALLBACK_ISOLATED,
    ISOLATED_EXAMPLE_LITERALS,
    LEGACY_EXAMPLE_LITERALS,
    load_prompt,
    load_stage_prompt,
    proposal_example_literals,
    render_available_models,
)

#: sha256 of each template at the base SHA c991d6f6 — the bytes every
#: pre-U3 run rendered. Captured via `git show c991d6f6:<path> | sha256sum`.
PRE_U3_TEMPLATE_SHA = {
    "comparison_stage.md": "f4ef2657e9e499882bfabed0e47211abe802bcf88c38476427fe24aa7da04b48",
    "causal_reasoning_stage.md": "b153695681665b847e312a705985ad8654106e7bc932d18325640768420835f0",
}

BUNDLED_NAMES = ("punet", "fcnet", "transformer", "wavenet", "rnn", "gated_fno")
_BUNDLED_RE = re.compile(r"\b(" + "|".join(BUNDLED_NAMES) + r")\b", re.IGNORECASE)

STAGES = ("comparison_stage", "causal_reasoning_stage", "proposing_stage")
MODES = ("explore", "exploit")


class _Meta:
    def __init__(self, name: str) -> None:
        self.name = name
        self.capability_type = "model"
        self.created_at = "2026-08-24T00:00:00+00:00"
        self.source_iteration = "iter_001"
        self.description = "An agent-generated architecture."
        self.mathematical_definition = "y = f(x)"


class _Registry:
    def __init__(self, names: tuple[str, ...] = ()) -> None:
        self._names = names

    def list(self, capability_type: str):
        assert capability_type == "model"
        return [_Meta(n) for n in self._names]


class TestLegacyRenderIsByteIdentical:
    def test_legacy_literals_reproduce_the_pre_u3_template_bytes(self):
        for name, sha in PRE_U3_TEMPLATE_SHA.items():
            text = load_prompt(name)
            for key, value in LEGACY_EXAMPLE_LITERALS.items():
                text = text.replace("{" + key + "}", value)
            if name == "causal_reasoning_stage.md":
                # PR552 deliberately adds missing-baseline guidance. Keep the
                # historical byte oracle for EVERYTHING ELSE, and pin the
                # exact declared delta rather than recapturing the whole file.
                current = (
                    "   NUMERICAL OUTCOME. If no observed baseline exists, set current_value to null\n"
                    "   and state an absolute prediction; do not invent a SOTA or relative gain.\n"
                    "   With an observed baseline, the boldness (abs(predicted - current) / abs(current))"
                )
                previous = (
                    "   NUMERICAL OUTCOME. The boldness (abs(predicted - current) / abs(current))"
                )
                # PR588 deliberately explains citation identities. Pin and remove
                # that exact addition before checking the original byte oracle.
                citation_guidance = (
                    "For `inherited_components`, copy the actual source identity. An `experiment`\n"
                    "uses its bare `model_type`. An `external_agent` uses the originating expert\n"
                    "item's `source_ref`, for example `arxiv:2312.00752`; a `human` source uses\n"
                    "its supplied instruction ID, for example `human:instruction_20260603`.\n"
                    "Both non-experiment types require `prefix:identifier`; a bare `iter_004`\n"
                    "is not a valid external citation. These are format examples, not sources\n"
                    "to invent: use them only when the corresponding source was supplied.\n\n"
                )
                assert text.count(citation_guidance) == 1
                text = text.replace(citation_guidance, "")
                assert text.count(current) == 1
                text = text.replace(current, previous)
            assert hashlib.sha256(text.encode("utf-8")).hexdigest() == sha, (
                f"{name}: the non-isolated render no longer reproduces the pre-U3 bytes"
            )

    def test_default_stage_render_carries_the_legacy_example(self):
        rendered = load_stage_prompt("comparison_stage")
        assert '"model_type": "wavenet"' in rendered
        assert "5.57" in rendered
        assert "{example_" not in rendered

    def test_the_legacy_empty_fallback_is_untouched(self):
        assert render_available_models(_Registry()) == _MODEL_REGISTRY_EMPTY_FALLBACK
        assert "wavenet, punet, fcnet" in _MODEL_REGISTRY_EMPTY_FALLBACK

    def test_the_legacy_nonempty_header_line_is_byte_identical(self):
        """The one edited sentence, pinned verbatim from the base bytes."""
        # The phantom filter drops entries absent from the live
        # MODEL_REGISTRY; register the stub name so the non-empty branch
        # renders (the filter's own tests live elsewhere).
        with patch.dict("ml_models.models_sandbox.MODEL_REGISTRY", {"my_tcn": object()}):
            block = render_available_models(_Registry(("my_tcn",)))
        assert (
            "The agent-generated model registry currently contains the following "
            "models, sorted most-recent first. You may **reuse** an existing "
            "entry by name (set ``baseline_config.model_config.model_name`` to "
            "the entry's name) OR **propose** a new architecture OR **use a "
            "built-in** model_type — see the 3-branch rule in the Rules section "
            "below."
        ) in block


def _census(text: str, *, where: str) -> list[str]:
    problems = []
    hit = _BUNDLED_RE.search(text)
    if hit:
        problems.append(f"{where}: bundled architecture name {hit.group(0)!r}")
    if "5.57" in text:
        problems.append(f"{where}: baseline SOTA figure 5.57")
    if re.search(r"\b323\b", text):
        problems.append(f"{where}: FCNet-scale literal 323")
    if "{example_" in text:
        problems.append(f"{where}: unsubstituted example token")
    return problems


class TestIsolatedRenderNamesNoBaseline:
    def test_every_stage_and_mode_is_clean_under_isolation(self):
        problems: list[str] = []
        for stage in STAGES:
            for mode in MODES:
                rendered = load_stage_prompt(
                    stage,
                    exploration_mode=mode,
                    template_vars={
                        "available_models_block": render_available_models(
                            _Registry(), baseline_isolation=True
                        ),
                    },
                    baseline_isolation=True,
                )
                problems += _census(rendered, where=f"{stage}/{mode}")
        assert not problems, "\n".join(problems)

    def test_the_registry_block_is_clean_under_isolation(self):
        with patch.dict("ml_models.models_sandbox.MODEL_REGISTRY", {"my_tcn": object()}):
            nonempty = render_available_models(_Registry(("my_tcn",)), baseline_isolation=True)
        isolated_empty = render_available_models(_Registry(), baseline_isolation=True)
        for block in (isolated_empty, nonempty):
            assert not _census(block, where="registry block"), block
        assert isolated_empty == _MODEL_REGISTRY_EMPTY_FALLBACK_ISOLATED
        assert "bundled built-in model types are not available in this run" in nonempty
        assert "**use a built-in**" not in nonempty


class TestExampleLiteralAuthorities:
    def test_the_isolated_literals_are_neutral(self):
        assert ISOLATED_EXAMPLE_LITERALS == {
            "example_model_type": "exemplar",
            "example_model_type_capitalized": "Exemplar",
            "example_sota_score": "1.23",
        }
        for value in ISOLATED_EXAMPLE_LITERALS.values():
            assert not _BUNDLED_RE.search(value)
            assert "5.57" not in value

    def test_the_selector_returns_the_declared_sets(self):
        assert proposal_example_literals(baseline_isolation=False) == LEGACY_EXAMPLE_LITERALS
        assert proposal_example_literals(baseline_isolation=True) == ISOLATED_EXAMPLE_LITERALS
