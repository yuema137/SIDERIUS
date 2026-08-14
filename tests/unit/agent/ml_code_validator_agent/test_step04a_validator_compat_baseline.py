"""CHECKPOINT 0 — validator-verdict and prior-plugin compatibility baselines.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §5 (Stage-A parity rows
*"validator verdicts on fixture plugins"* and *"prior on-disk plugin
loadability"*, both **CAPTURE FIRST**), §16 C1, and OD-S4-3 (preserve
loadability; no workspace boundary).

**The defects only this module catches.**

``_check_instantiation_and_gradient`` is about to stop reading a module
constant for its class count and start deriving one from the normalized
contract. Three regressions become possible and none is covered elsewhere:

* a verdict FLIPS for an unchanged plugin — the probe now builds a
  differently-shaped input, so a candidate that validated yesterday is
  rejected today (or worse, the reverse);
* an error MESSAGE stops naming the shape it judged against, which is the
  only thing telling an operator why a candidate died;
* the legacy ``_DEFAULT_OUTPUT_TYPE`` fallback quietly stops working. No
  plugin on disk exercises it (parent §18: 89/89 declare the field), so the
  corpus cannot protect it and a synthetic fixture must.

Captured at ``3e9728c8``, clean tree, before any PR-04a production edit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ml_models import plugin_loader
from nodes.ml_code_validator_agent import _check_instantiation_and_gradient
from tests.helpers.golden import assert_json_golden

GOLDENS = Path(__file__).parent / "goldens"

REPO_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_CORPUS = REPO_ROOT / "agent_generated" / "models"


# ---------------------------------------------------------------------------
# Fixture plugins — hand-written, minimal, and each one a distinct verdict class
# ---------------------------------------------------------------------------

_HEADER = """\
import torch
import torch.nn as nn
from pydantic import BaseModel, Field

PLUGIN_MODEL_TYPE = "{name}"


class Cfg(BaseModel):
    model_type: str = Field(default="{name}")
    segmentation_size: int = Field(default=64, ge=1)
    batch_size: int = Field(default=1, ge=1)


PLUGIN_CONFIG_CLASS = Cfg


class Net(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.emb = nn.Embedding(256, 8)
        self.head = nn.Conv1d(8, {out_channels}, kernel_size=1)

    def forward(self, x):
        out = self.emb(x).permute(0, 2, 1)
        out = self.head(out)
        return {return_expr}


PLUGIN_MODEL_CLASS = Net
"""


def _plugin_source(name: str, *, out_channels: int, squeeze: bool, declaration: str | None) -> str:
    src = _HEADER.format(
        name=name,
        out_channels=out_channels,
        return_expr="out.squeeze(1)" if squeeze else "out",
    )
    if declaration is not None:
        src += f'PLUGIN_OUTPUT_TYPE = "{declaration}"\n'
    return src


#: (case id, out_channels, squeeze, declaration). Each row is a verdict class
#: the derivation must reproduce, not a variation on one.
_FIXTURE_CASES: list[tuple[str, int, bool, str | None]] = [
    # honours a classifier declaration -> full pass
    ("classifier_ok", 256, False, "classifier"),
    # honours a regressor declaration -> full pass on the non-class branch
    ("regressor_ok", 1, True, "regressor"),
    # NO declaration: the intentional legacy fallback (parent §18). The only
    # thing standing between `_DEFAULT_OUTPUT_TYPE` and silent removal.
    ("legacy_no_declaration", 256, False, None),
    # an unrecognised declaration must FAIL CLOSED, never coerce to classifier
    ("illegal_declaration", 256, False, "regression"),
    # declares classifier, emits the regressor shape -> shape rejection whose
    # message must name the expected shape
    ("declaration_shape_mismatch", 1, True, "classifier"),
]


def _verdict(tmp_path: Path, case: tuple[str, int, bool, str | None]) -> dict:
    case_id, out_channels, squeeze, declaration = case
    path = tmp_path / f"s04a_{case_id}.py"
    path.write_text(
        _plugin_source(
            f"s04a_{case_id}", out_channels=out_channels, squeeze=squeeze, declaration=declaration
        ),
        encoding="utf-8",
    )
    inst_ok, grad_ok, otype_ok, err, total, trainable = _check_instantiation_and_gradient(str(path))
    return {
        "case": case_id,
        "instantiation_ok": inst_ok,
        "gradient_ok": grad_ok,
        "output_type_ok": otype_ok,
        "error": err,
        "realized_total_parameter_count": total,
        "realized_trainable_parameter_count": trainable,
    }


def test_validator_verdicts_match_the_captured_baseline(tmp_path):
    """Every fixture's full verdict tuple and error text is pinned.

    Fails when: a verdict boolean flips, a parameter count changes, or an
    error message stops naming the shape/legal values it judged against.
    The error strings carry no filesystem path by construction, so the
    golden is portable across checkouts.
    """
    observed = [_verdict(tmp_path, case) for case in _FIXTURE_CASES]
    assert_json_golden(
        observed,
        GOLDENS / "s04a_validator_verdicts.json",
        surface="S04a-C0 validator verdicts on fixture plugins",
    )


def test_legacy_undeclared_plugin_still_resolves_through_the_fallback(tmp_path):
    """The ``_DEFAULT_OUTPUT_TYPE`` path is reachable and is what runs.

    Separate from the golden above because the golden proves the *verdict*;
    this proves the *reason*. A future change could keep the verdict green
    by, say, treating a missing declaration as a regressor whose 3-D output
    happened to pass some looser check. Asserting the module truly declares
    nothing, and that the classifier-shaped forward is what satisfies the
    probe, pins the fallback semantics rather than its side effect.

    Fails when: the fallback is deleted, or its value changes.
    """
    path = tmp_path / "s04a_fallback_probe.py"
    path.write_text(
        _plugin_source("s04a_fallback_probe", out_channels=256, squeeze=False, declaration=None),
        encoding="utf-8",
    )
    assert "PLUGIN_OUTPUT_TYPE" not in path.read_text(encoding="utf-8")

    inst_ok, grad_ok, otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
        str(path)
    )
    assert (inst_ok, grad_ok, otype_ok, err) == (True, True, True, None)

    # And the mirror case: an undeclared plugin emitting the REGRESSOR shape
    # must be rejected, because the fallback is classifier. If it passed, the
    # fallback would have become "whatever the model happens to emit".
    regressor_shaped = tmp_path / "s04a_fallback_negative.py"
    regressor_shaped.write_text(
        _plugin_source("s04a_fallback_negative", out_channels=1, squeeze=True, declaration=None),
        encoding="utf-8",
    )
    inst_ok, _grad_ok, _otype_ok, err, _t, _tt = _check_instantiation_and_gradient(
        str(regressor_shaped)
    )
    assert inst_ok is False
    assert err is not None and "does not match expected" in err


# ---------------------------------------------------------------------------
# Prior-plugin loadability (OD-S4-3)
# ---------------------------------------------------------------------------


def _corpus() -> list[Path]:
    if not PLUGIN_CORPUS.is_dir():
        return []
    return sorted(p for p in PLUGIN_CORPUS.glob("*.py") if p.name != "__init__.py")


def test_every_prior_generated_plugin_still_loads_and_registers():
    """Every plugin present in THIS checkout imports and registers.

    OD-S4-3 chose preservation over a workspace boundary, so this is the
    compatibility oracle for that decision. It enumerates at run time and
    pins no count: ``agent_generated/models/`` is a live, gitignored
    directory that grows with every real chain run, so a literal count would
    be a false failure the day after it was written (parent §18).

    Fails when: a PR-04a change makes any previously-written plugin
    unimportable or unregisterable — the exact regression OD-S4-3 forbids.

    Skips (with a reason, never silently) when the corpus is absent — CI
    runners have no generated plugins, and the requirement is declared here
    rather than papered over with a fallback path.
    """
    corpus = _corpus()
    if not corpus:
        pytest.skip(
            f"no generated-plugin corpus at {PLUGIN_CORPUS} — this oracle is "
            "meaningful only in a checkout that has run the chain (CI has none)"
        )

    failures: list[str] = []
    registered: list[str] = []
    for path in corpus:
        try:
            name = plugin_loader.register_model_in_memory(str(path))
        except Exception as exc:  # any failure at all is a finding, not a crash
            failures.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        if name is None:
            failures.append(f"{path.name}: register_model_in_memory returned None")
        else:
            registered.append(name)

    print(
        f"[S04a-C0] plugin corpus at {PLUGIN_CORPUS}: {len(corpus)} files, "
        f"{len(registered)} registered, {len(failures)} failed"
    )
    assert not failures, "prior generated plugins no longer load:\n" + "\n".join(failures)
    assert len(registered) == len(corpus)


def test_corpus_declaration_census_is_recorded():
    """Report the corpus composition the ledger quotes, and pin nothing else.

    The census exists so the PR can re-enumerate at closeout and compare
    against Checkpoint 0. It asserts only what OD-S4-3 actually requires:
    every file parses. Counts are printed, never pinned — see above.
    """
    corpus = _corpus()
    if not corpus:
        pytest.skip(f"no generated-plugin corpus at {PLUGIN_CORPUS}")

    import ast

    declaring = 0
    unparseable: list[str] = []
    by_declaration: dict[str, int] = {}
    for path in corpus:
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            unparseable.append(f"{path.name}: {exc}")
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PLUGIN_OUTPUT_TYPE" for t in node.targets
            ):
                declaring += 1
                if isinstance(node.value, ast.Constant):
                    key = str(node.value.value)
                    by_declaration[key] = by_declaration.get(key, 0) + 1
                break

    print(
        f"[S04a-C0] census: {len(corpus)} examined, {declaring} declare "
        f"PLUGIN_OUTPUT_TYPE, {len(corpus) - declaring} lacking, "
        f"{len(unparseable)} unparseable, by declaration: {sorted(by_declaration.items())}",
        file=sys.stderr,
    )
    assert not unparseable, "generated plugins that no longer parse:\n" + "\n".join(unparseable)
