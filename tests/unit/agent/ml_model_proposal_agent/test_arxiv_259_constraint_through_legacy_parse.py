"""#259 constraint exercised THROUGH the real legacy parse path (behavioral).

Supervisor caution at the campaign convergence: the #296-proposer ×
output-type-constraint interplay is where a behavioural union can look like
a clean textual merge — so the constraint must be proven THROUGH the parse
site both changes now share, not only schema-direct. The schema-direct tests
and the count-exact source census live in
``test_arxiv_259_output_type_constraint.py``; the two tests here own the one
class those cannot: a runtime interaction inside ``_run_legacy``'s own flow
(prompt build → bridge → raw → default resolution → ``model_validate`` with
context) breaking the constraint while every direct/census assertion stays
green.
"""

from __future__ import annotations

import importlib

import pytest

from agent.schemas.proposal import ProposalInput

# The node package rebinds its own name in sys.modules (the same load-bearing
# pattern S11 documented on the lit-review node), so `import a.b.b as m`
# fails; importlib resolves the registered module.
node_mod = importlib.import_module("nodes.ml_model_proposal_agent.ml_model_proposal_agent")
MLModelProposalAgent = node_mod.MLModelProposalAgent


class _StubBridge:
    """Returns one canned reasoning string and one canned raw proposal."""

    def __init__(self, raw: dict):
        self._raw = raw

    def generate_text(self, *a, **k) -> str:
        return "stub reasoning"

    def generate(self, *a, **k) -> dict:
        return dict(self._raw)


def _agent(raw: dict, tmp_path) -> MLModelProposalAgent:
    return MLModelProposalAgent(
        bridge_factory=lambda *a, **k: _StubBridge(raw),
        capability_index_path=str(tmp_path / "cap_index.json"),
    )


def _inp(allowed) -> ProposalInput:
    return ProposalInput.model_validate(
        {
            "interpretation_evidence": {},
            "existing_model_types": ["wavenet"],
            "allowed_output_types": allowed,
            # A complete forward contract: the commit-prompt renderer refuses
            # an empty one BEFORE the bridge, and the parse under test never
            # runs.
            "forward_contract": {
                "input_shape": "[B, T] int64",
                "output_shape": "[B, 256, T] float32",
                "output_description": "per-timestep class logits",
            },
        }
    )


@pytest.fixture(autouse=True)
def _no_preflight(monkeypatch):
    # The static-VRAM advisory is not the property under test; stubbed on the
    # module that calls it (the node's public-boundary recipe).
    monkeypatch.setattr(node_mod, "_run_preflight_check", lambda *a, **k: None)


RAW_NO_OUTPUT_TYPE = {
    "model_name": "parse_path_probe",
    "model_description": "d",
    "mathematical_definition": "m",
    "motivation": "mo",
    "expert_advice": {},
    "baseline_config": {},
}


def test_omitted_key_takes_the_single_constraint_default_through_run_legacy(tmp_path):
    """Defect only this catches: the parse site resolving the omitted key
    before/without the constraint-aware default (e.g. a #296-era reorder
    rebuilding ``raw`` after the default line) — schema-direct tests cannot
    see it because they never run the parse. Fails by: output_type
    'classifier' (the legacy literal) instead of the declared single type."""
    out = _agent(RAW_NO_OUTPUT_TYPE, tmp_path)._run_legacy(_inp(("regressor",)))
    assert out.output_type == "regressor"


def test_out_of_set_value_is_refused_through_run_legacy(tmp_path):
    """Defect only this catches: the parse site's model_validate losing the
    constraint context key at runtime (census counts the source token; this
    proves the CALL). Fails by: a classifier proposal returning under a
    regressor-only declaration."""
    raw = dict(RAW_NO_OUTPUT_TYPE, output_type="classifier")
    with pytest.raises(Exception, match=r"allowed_output_types=\('regressor',\)"):
        _agent(raw, tmp_path)._run_legacy(_inp(("regressor",)))


def test_unconstrained_legacy_default_is_unchanged_through_run_legacy(tmp_path):
    """Defect only this catches: the constraint machinery leaking into the
    UNCONSTRAINED path at the parse site (default no longer 'classifier').
    Fails by: any refusal or a non-classifier default with allowed=None."""
    out = _agent(RAW_NO_OUTPUT_TYPE, tmp_path)._run_legacy(_inp(None))
    assert out.output_type == "classifier"
