"""F-C12P-CP12-1 — the health-config cache must not define composition authority.

**The invariant**: for the same composed task / health configuration, a COLD
process and a WARM one must resolve the SAME authority. ``_CACHED_GATES``
(``execute_tools/health_checks/config.py``) may skip work whose result is
already in hand; it may never skip the work whose *side effects* are what a
health resolution establishes.

**The defect only this file catches.** ``load_health_gates_config`` used to
return early on a warm default-path cache — a memo keyed on NOTHING, and so
able to hand back a value composed under a *different* binding — before
calling ``load_composed_health_config``. Composing is not only a computation
— it BINDS. It resolves the task's Health plugin set into this process's run
scope (``_plugin_binding.load_task_health_plugins``, which is what makes the
FIRST resolution authoritative for the whole process) and it replaces the
regime-A fact derivation with the task's DECLARED facts
(``_plugin_binding.resolve_task_health_bindings`` → ``_TASK_FACTS``). Those
two globals are cleared on their own lifecycle, independently of the config
cache, so the early return made both outcomes depend on cache warmth:

* a legacy TIDMAD resolution bound ``value_scale_unit="mV"`` and
  ``symbol_cardinality=256`` in a cold process and ``None`` — the regime-A
  fallback — in a warm one;
* a run whose first health resolution bound nothing then let a SECOND,
  different task family bind past the run-scope guard, so a composed run
  succeeded warm and was refused cold.

Nothing else can catch it. Every other test in this family shares one
interpreter, and it is precisely the shared interpreter that hides the defect
— which is why every process here is a genuinely separate one.

**The repair is a KEY, not the removal of the memo.** The memo is keyed on
``config._resolved_binding_identity`` — the run-scoped binding state read
from memory. Cold misses; warm under the SAME binding hits, because
recomposing could not reach a different result or a different bind; warm
under a DIFFERENT binding misses *by construction* and the run-scope guard
fires exactly as it does cold. That keeps the invariant above while a
composition that costs milliseconds stops running on all 17 call sites,
several of them per gate evaluation.

**How these tests fail when the behaviour breaks.** Restore the un-keyed
early return (``if path is None and _CACHED_GATES is not None: return
_CACHED_GATES``) and:
``test_a_warm_cache_binds_the_same_task_facts_as_a_cold_process`` fails with
the warm process reporting ``task_facts=None`` against the cold process's
declared TIDMAD facts;
``test_a_warm_cache_cannot_smuggle_a_second_family_past_the_run_scope_guard``
fails because the warm process returns ``outcome="ok"`` with Pets bound while
the cold process raises ``HealthPluginRunScopeError``; and
``test_a_warm_cache_under_a_changed_binding_recomposes`` fails because the
process reports ``rebound=False`` — the stale instance served under a binding
it was not composed under, which is the defect stated as a memo property
rather than as a symptom.

**The second half — who binds FIRST.** Making the cache honest makes the
underlying question deterministic: with no effective config to read
(``health_gate_enabled=False``) the tuner's task-render step reached the
binding-less loader BEFORE it resolved its own scientific gate set, so a
composed run bound TIDMAD's family and was then refused its own.
``test_the_tuners_first_health_resolution_binds_the_runs_own_family`` owns
that, and its call site's reachability is owned by
``tests/unit/workflows/test_step12_pr12a_c7_prompt_science.py`` — which drives
the real ``agent.run()`` and goes red the moment that site stops asking the
run's declaration.

The run-scope guard is a DETECTOR, not the defect: it is neither weakened nor
special-cased here, and ``test_the_run_scope_guard_stays_discriminative``
proves it still tells a re-bind of the same family from a different one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Hand-written from ``configs/task_health/tidmad.yaml``, NOT read back from
#: the loader under test.
TIDMAD_DECLARED_FACTS = {
    "encoding_family": "int8_symbol_stream",
    "file_group_size": 20,
    "sampling_frequency_hz": 10000000.0,
    "symbol_cardinality": 256,
    "value_scale_unit": "mV",
}

#: Hand-written from ``examples/oxford_iiit_pet/declared/task_health.yaml``.
PETS_PLUGIN_REF = "../plugins/_pets_health_views.py"

_PROBE = r"""
import json, sys
REPO = sys.argv[1]
import execute_tools.health_checks.config as cfg_mod
assert cfg_mod.__file__.startswith(REPO), "WRONG CHECKOUT: " + cfg_mod.__file__
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.candidate_eligibility import resolve_run_scientific_gate_ids
from workflows.task_composition import compose_run_task_bindings
assert _plugin_binding.__file__.startswith(REPO), "WRONG CHECKOUT"

def binding(task):
    return compose_run_task_bindings(
        REPO + "/tests/fixtures/step10_p1/" + task + "/composition.yaml"
    ).task_health_binding

def observe(out):
    facts = _plugin_binding.bound_task_facts()
    out["plugins"] = [p.canonical_identity() for p in _plugin_binding.loaded_plugin_set()]
    out["task_facts"] = None if facts is None else facts.model_dump(mode="json")

scenario = sys.argv[2]
out = {"scenario": scenario}
try:
    if scenario == "legacy_cold":
        out["gate_ids"] = [g.id for g in cfg_mod.load_health_gates_config().health_gates]
    elif scenario == "legacy_warm":
        cfg_mod.load_health_gates_config()
        _plugin_binding.reset_run_scope()          # the run boundary; cache untouched
        out["gate_ids"] = [g.id for g in cfg_mod.load_health_gates_config().health_gates]
    elif scenario == "changed_binding_recomposes":
        first = cfg_mod.load_health_gates_config()
        out["first_bound"] = _plugin_binding.bound_task_facts() is not None
        _plugin_binding.reset_run_scope()           # the binding is now a DIFFERENT one
        out["cleared"] = _plugin_binding.bound_task_facts() is None
        second = cfg_mod.load_health_gates_config() # memo MISS -> recompose -> rebind
        out["rebound"] = _plugin_binding.bound_task_facts() is not None
        out["recomposed_new_instance"] = second is not first
        third = cfg_mod.load_health_gates_config()  # binding unchanged -> memo HIT
        out["repeat_is_memo_hit"] = third is second
        out["gate_ids"] = [g.id for g in second.health_gates]
    elif scenario == "composed_cold":
        cfg_mod.load_health_gates_config()
        out["gates"] = sorted(resolve_run_scientific_gate_ids(binding("pets")) or [])
    elif scenario == "composed_warm":
        cfg_mod.load_health_gates_config()
        _plugin_binding.reset_run_scope()          # the run boundary; cache untouched
        cfg_mod.load_health_gates_config()         # warm hit — must still compose
        out["gates"] = sorted(resolve_run_scientific_gate_ids(binding("pets")) or [])
    elif scenario in ("tuner_composed", "tuner_uncomposed"):
        from types import SimpleNamespace
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _resolve_run_gate_ids,
            _resolve_run_health_config,
        )
        ref = (
            None
            if scenario == "tuner_uncomposed"
            else SimpleNamespace(task_health_binding=binding("pets"))
        )
        inp = SimpleNamespace(health_checks_config=None, task_composition_ref=ref)
        out["gate_ids"] = [g.id for g in _resolve_run_health_config(inp).health_gates]
        out["gates"] = sorted(_resolve_run_gate_ids(inp) or [])
    elif scenario == "guard_same_family":
        resolve_run_scientific_gate_ids(binding("pets"))
        out["gates"] = sorted(resolve_run_scientific_gate_ids(binding("pets")) or [])
    elif scenario == "guard_other_family":
        resolve_run_scientific_gate_ids(binding("pets"))
        out["gates"] = sorted(resolve_run_scientific_gate_ids(binding("davis")) or [])
    else:
        raise SystemExit("unknown scenario " + scenario)
    out["outcome"] = "ok"
except Exception as exc:
    out["outcome"] = "raised"
    out["exc_type"] = type(exc).__name__
    out["exc"] = str(exc)[:600]
observe(out)
print("CP12_JSON " + json.dumps(out, sort_keys=True))
"""


def _run(scenario: str) -> dict:
    """Run one scenario in a genuinely separate interpreter.

    A monkeypatched global is not a cold process: the whole failure class is
    module state surviving across resolutions, so the isolation has to be a
    real process boundary.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(REPO_ROOT), scenario],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=300,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("CP12_JSON ")]
    assert lines, (
        f"probe {scenario!r} produced no result line\n"
        f"rc={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    return json.loads(lines[-1][len("CP12_JSON ") :])


@pytest.fixture(scope="module")
def observations() -> dict[str, dict]:
    scenarios = (
        "legacy_cold",
        "legacy_warm",
        "changed_binding_recomposes",
        "composed_cold",
        "composed_warm",
        "guard_same_family",
        "guard_other_family",
        "tuner_composed",
        "tuner_uncomposed",
    )
    return {s: _run(s) for s in scenarios}


def test_a_warm_cache_binds_the_same_task_facts_as_a_cold_process(observations):
    """A warm cache must not downgrade the task's DECLARED facts to regime-A.

    Fails, when the early return is restored, with the warm process reporting
    ``task_facts=None`` — no ``value_scale_unit``, so a millivolt threshold
    would be evaluated against the derived fallback — while the cold process
    reports TIDMAD's declared facts.
    """
    cold = observations["legacy_cold"]
    warm = observations["legacy_warm"]

    assert cold["outcome"] == "ok", cold
    assert warm["outcome"] == "ok", warm

    # Hardcoded, not read back from the loader under test.
    assert cold["task_facts"] == TIDMAD_DECLARED_FACTS
    assert warm["task_facts"] == TIDMAD_DECLARED_FACTS

    # ...and the full resolution is identical, not merely the facts.
    assert warm["gate_ids"] == cold["gate_ids"]
    assert warm["plugins"] == cold["plugins"]


def test_a_warm_cache_under_a_changed_binding_recomposes(observations):
    """The memo must MISS when the binding it was composed under is gone.

    This is the invariant restated as a property of the KEY rather than as a
    symptom of one caller. The two tests around it observe consequences —
    downgraded facts, a smuggled second family; this one observes the
    mechanism, and it is what goes red if the memo is ever re-keyed on
    nothing again.

    Fails, when the un-keyed early return is restored, at ``rebound`` — the
    warm call returns the instance composed under the *previous* binding and
    establishes no binding at all, so the process is left with
    ``bound_task_facts() is None`` while holding a config that only a bound
    TIDMAD resolution could have produced.

    ``repeat_is_memo_hit`` is the anti-vacuity half, and it is what makes
    this a REFINEMENT rather than the removal of the cache: a key that
    always missed would satisfy every other assertion here while putting the
    ~3.3 ms composition back on all 17 call sites. Under an unchanged
    binding the call must still be memo-served.
    """
    obs = observations["changed_binding_recomposes"]
    assert obs["outcome"] == "ok", obs

    assert obs["first_bound"] is True, obs
    assert obs["cleared"] is True, obs

    # The memo missed and the composition ran again — the whole point.
    assert obs["rebound"] is True, obs
    assert obs["recomposed_new_instance"] is True, obs

    # ...and the recomposed authority is the real one, hand-written from
    # configs/task_health/tidmad.yaml, not read back from the loader.
    assert obs["task_facts"] == TIDMAD_DECLARED_FACTS
    assert obs["gate_ids"] == [
        "output_diversity_blocking",
        "output_std_blocking",
        "amplitude_collapse_blocking",
        "pearson_dispersion_recording",
        "spectral_peak_ratio_recording",
        "per_file_output_std_recording",
    ]

    # Anti-vacuity: an unchanged binding is still served from the memo.
    assert obs["repeat_is_memo_hit"] is True, obs


def test_the_memo_key_observes_every_run_scoped_binding_global():
    """The key must cover exactly the state a composition establishes.

    ``_resolved_binding_identity`` is sound only while it observes every
    run-scoped global that composing BINDS. ``reset_run_scope`` is the
    existing authority on what that set is — it is the function whose job is
    to undo a bind — so the two are compared against each other rather than
    against a list written here.

    The defect only this catches: a fourth run-scoped binding global added to
    ``_plugin_binding`` (and dutifully cleared by ``reset_run_scope``) that
    the memo key does not read. Nothing else notices — every scenario above
    keeps passing, because they exercise the three axes that already exist,
    while a warm cache silently serves a value composed under a different
    binding along the new one.
    """
    import ast

    binding_src = (REPO_ROOT / "execute_tools" / "health_checks" / "_plugin_binding.py").read_text()
    config_src = (REPO_ROOT / "execute_tools" / "health_checks" / "config.py").read_text()

    def _fn(source: str, name: str) -> ast.FunctionDef:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"{name!r} not found — it was renamed or removed")

    cleared: set[str] = set()
    for node in ast.walk(_fn(binding_src, "reset_run_scope")):
        if isinstance(node, ast.Global):
            cleared.update(n for n in node.names if n.startswith("_"))
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "clear"
            and isinstance(node.value, ast.Name)
            and node.value.id.startswith("_")
        ):
            cleared.add(node.value.id)

    observed = {
        node.attr
        for node in ast.walk(_fn(config_src, "_resolved_binding_identity"))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "_plugin_binding"
        and node.attr.startswith("_")
    }

    assert cleared == {"_RUN_SCOPE", "_TASK_FACTS", "_VIEW_BINDINGS"}, (
        f"reset_run_scope now clears {sorted(cleared)}. The run-scoped binding "
        f"surface changed; _resolved_binding_identity must be re-derived, not "
        f"this literal updated."
    )
    assert observed == cleared, (
        f"the memo key reads {sorted(observed)} but a composition binds "
        f"{sorted(cleared)}. A warm cache would serve a value composed under a "
        f"different binding along {sorted(cleared - observed)}."
    )


def test_a_warm_cache_cannot_smuggle_a_second_family_past_the_run_scope_guard(observations):
    """Cache warmth must not decide whether the run-scope guard sees a bind.

    A process that has already resolved the framework/default health
    configuration has bound a family. A composed task binding a DIFFERENT one
    afterwards is exactly what the guard exists to refuse — and whether that
    first bind happened must be a fact about the run, never about the cache.

    Fails, when the early return is restored, with the warm process reporting
    ``outcome="ok"`` and Pets' gate set while the cold process raises
    ``HealthPluginRunScopeError``: the same declaration, two different
    authorities, decided by nothing the operator can see.
    """
    cold = observations["composed_cold"]
    warm = observations["composed_warm"]

    assert cold["outcome"] == warm["outcome"], (cold, warm)
    assert cold.get("exc_type") == warm.get("exc_type"), (cold, warm)
    assert cold["plugins"] == warm["plugins"], (cold, warm)
    assert cold["task_facts"] == warm["task_facts"], (cold, warm)

    # The guard is the DETECTOR and must have fired in BOTH, not neither:
    # an equality that held because the fix silenced the guard would be the
    # opposite of this fix.
    assert cold["outcome"] == "raised"
    assert cold["exc_type"] == "HealthPluginRunScopeError"


def test_the_tuners_first_health_resolution_binds_the_runs_own_family(observations):
    """The FIRST resolution in a tuner process must use the RUN's declaration.

    The first bind in a process is authoritative — the run-scope guard refuses
    every later, differing one. The tuner's first health resolution happens
    while building its task render, before it resolves its own scientific gate
    set, and it reaches the binding-less loader whenever the run materialized
    no effective config (``health_gate_enabled=False``). Composing
    ``LEGACY_OMITTED`` there bound TIDMAD's family into a composed run, which
    then had its OWN family refused moments later.

    Fails, when that site goes back to ``load_health_gates_config(...)``, with
    ``tuner_composed`` reporting TIDMAD's roster and then raising
    ``HealthPluginRunScopeError`` from ``_resolve_run_gate_ids`` — the same
    refusal a real cold composed run gets today.

    ``tuner_uncomposed`` is the parity half: a run with no composition must
    still resolve exactly the shipped legacy roster and facts.
    """
    composed = observations["tuner_composed"]
    legacy = observations["tuner_uncomposed"]

    assert composed["outcome"] == "ok", composed
    # Hand-written from examples/oxford_iiit_pet/declared/task_health.yaml.
    assert composed["gate_ids"] == [
        "pets_distinct_symbols_blocking",
        "pets_dominant_fraction_blocking",
    ]
    assert composed["gates"] == [
        "pets_distinct_symbols_blocking",
        "pets_dominant_fraction_blocking",
    ]
    assert [p["configured_ref"] for p in composed["plugins"]] == [PETS_PLUGIN_REF]

    assert legacy["outcome"] == "ok", legacy
    # Hand-written from configs/task_health/tidmad.yaml.
    assert legacy["gate_ids"] == [
        "output_diversity_blocking",
        "output_std_blocking",
        "amplitude_collapse_blocking",
        "pearson_dispersion_recording",
        "spectral_peak_ratio_recording",
        "per_file_output_std_recording",
    ]
    assert legacy["task_facts"] == TIDMAD_DECLARED_FACTS
    assert legacy["plugins"] == []


def test_the_run_scope_guard_stays_discriminative(observations):
    """The guard must still tell a re-bind of the SAME family from a different one.

    Anti-vacuity for the test above: if the guard had become a blanket refusal
    (or a blanket pass), the cold/warm equality there would be worthless.

    Fails if re-resolving the SAME family stops being idempotent (``same``
    reports ``raised``), or if a genuinely different family stops being
    refused (``other`` reports ``ok``).
    """
    same = observations["guard_same_family"]
    other = observations["guard_other_family"]

    assert same["outcome"] == "ok", same
    # Hand-written from examples/oxford_iiit_pet/declared/task_health.yaml.
    assert same["gates"] == [
        "pets_distinct_symbols_blocking",
        "pets_dominant_fraction_blocking",
    ]
    assert [p["configured_ref"] for p in same["plugins"]] == [PETS_PLUGIN_REF]

    assert other["outcome"] == "raised", other
    assert other["exc_type"] == "HealthPluginRunScopeError"
