"""Step 09.5a C5c — the BASE-vs-HEAD exact LLM-facing differential.

NOT a collected test: it is the harness for a one-time, reproducible
differential that closed the Gate-1 waiver. It is kept because the recipe is
the evidence — a result nobody can re-run is a claim, not a proof.

HOW TO RE-RUN
-------------
Both sides must execute, and both must be prepared IDENTICALLY:

    git worktree add --detach <base_wt> 14b7e22a
    git worktree add --detach <head_wt> <head>
    # both worktrees: share the machine-local registry and data config,
    # because they are gitignored state, not code
    ln -s <repo>/agent_generated <wt>/agent_generated
    cp <repo>/tidmad_data_config.yaml <wt>/
    cd <wt> && <repo>/.venv/bin/python this_file.py out.json

WHY BOTH SIDES MUST BE WORKTREES — a real finding, learned the hard way.
Running base in a worktree against HEAD in the main checkout produced a
16-call diff in the proposer's loss-registry block. It was NOT a regression:
`agent/prompt_templates/proposal/__init__.py:live_loss_metadata` keeps only
capability entries whose `file_path` sits in `_GLOBAL_LOSS_DIR`, and that
directory is derived from the tree root. A worktree's root differs from the
absolute paths stored in the (machine-local, mutable) capability index, so the
worktree filtered every loss out and rendered the empty fallback.

Equalising the code under test is not enough; the *environment the code reads*
must be equal too. Both sides in worktrees, sharing one `agent_generated`,
makes the mismatch identical on both sides and the comparison meaningful.

RESULT (base 14b7e22a vs head 7eba2131, production pipeline mode):
16 calls, 5,362,333 prompt bytes, sha256 f5d706385e18add4 on BOTH sides —
call count, order, labels, methods, system bytes, user bytes and structured
inputs all exact-equal.
"""

import hashlib
import inspect
import json
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO = Path.cwd()
sys.path.insert(0, str(REPO))

CAPTURES = []


def _norm(v, ws, dd):
    if isinstance(v, str):
        return v.replace(ws, "<WS>").replace(dd, "<DATA>")
    if isinstance(v, dict):
        return {k: _norm(x, ws, dd) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x, ws, dd) for x in v]
    if hasattr(v, "model_dump"):
        try:
            return _norm(v.model_dump(mode="json"), ws, dd)
        except Exception:
            return f"<{type(v).__name__}>"
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return f"<{type(v).__name__}>"


def make_bridge_factory(ws, dd):
    class _Recorder:
        def __init__(self, *a, **kw):
            pass

        def _rec(self, method, sysp, userp, kwargs):
            CAPTURES.append(
                {
                    "method": method,
                    "label": kwargs.get("label", "unlabeled"),
                    "system": _norm(sysp, ws, dd) if isinstance(sysp, str) else None,
                    "user": _norm(userp, ws, dd) if isinstance(userp, str) else None,
                    "kwargs": {
                        k: _norm(v, ws, dd) for k, v in sorted(kwargs.items()) if k != "label"
                    },
                }
            )

        def generate(self, system_prompt="", user_prompt="", **kw):
            self._rec("generate", system_prompt, user_prompt, kw)
            return {}

        def generate_text(self, system_prompt="", user_prompt="", **kw):
            self._rec("generate_text", system_prompt, user_prompt, kw)
            return ""

        def plan(self, *a, **kw):
            self._rec("plan", None, None, kw)
            return {}

        def reflect(self, *a, **kw):
            self._rec("reflect", None, None, kw)
            return {}

        def tool_call(self, system_prompt="", user_prompt="", **kw):
            self._rec("tool_call", system_prompt, user_prompt, kw)
            return {}

        def emit_marker(self, **kw):
            pass

        def __getattr__(self, name):
            def _any(*a, **kw):
                return {}

            return _any

    return lambda *a, **kw: _Recorder()


def main(out_path):
    from tests.unit.workflows.test_model_exploration import _write_tuning_output
    from workflows import model_exploration as me

    tmp = Path(tempfile.mkdtemp(prefix="parity_"))
    _write_tuning_output(tmp, "punet")
    ws = str(tmp / "ws")
    dd = str(tmp / "data")

    # Use a shipped llm_config so the proposer runs its PRODUCTION pipeline
    # mode (propose resolves to ProposalLLMConfig), not the legacy 2-call path.
    import json as _json

    from workflows.llm_config import WorkflowLLMConfig

    _cfg = WorkflowLLMConfig.model_validate(
        _json.loads(Path("llm_configs/openai_tiered_pro.json").read_text())
    )

    flat = dict(
        llm_config=_cfg,
        data_dir=dd,
        model_types=["punet"],
        source_run_name="v1",
        workspace=ws,
        run_name="parity",
        bridge_factory=make_bridge_factory(ws, dd),
    )
    params = inspect.signature(me.run_workflow).parameters
    if "launch" in params:
        from workflows.run_config import WorkflowLaunchConfig, launch_config_field_names

        fields = launch_config_field_names()
        lk = {k: v for k, v in flat.items() if k in fields}
        rk = {k: v for k, v in flat.items() if k not in fields}

        def call():
            return me.run_workflow(launch=WorkflowLaunchConfig(**lk), **rk)

    else:

        def call():
            return me.run_workflow(**flat)

    err = None
    try:
        call()
    except Exception as e:
        err = f"{type(e).__name__}"
    payload = {"captures": CAPTURES, "terminated_with": err}
    Path(out_path).write_text(json.dumps(payload, indent=1, sort_keys=True))
    digest = hashlib.sha256(json.dumps(CAPTURES, sort_keys=True).encode()).hexdigest()
    print(f"calls={len(CAPTURES)} terminated={err} sha256={digest[:16]}")


if __name__ == "__main__":
    main(sys.argv[1])
