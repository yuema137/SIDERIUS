"""Checkpoint L Gate 1 — Real-LLM smoke test for the loss-inventory feature.

Constructs a hand-crafted ``CustomLossSpec`` (the fully-differentiable
``expected_value_mse`` candidate), calls
``MLModelImplementor._generate_loss`` with a REAL LLM bridge, and verifies
the assembled loss plugin compiles + passes the dummy-tensor check.

Estimated cost: ~$0.05-0.20 (one reasoning call + one code call to the
implementor LLM; optionally one repair call).
Estimated wall time: ~2-5 min.

This script is gated by ``docs/gates/gate_testing_standard.md`` Gate 1
("Real LLM + pseudo training") — needs operator approval before running.

Run:
    .venv/bin/python scripts/checkpoint_l_gate1.py \\
        --llm_config llm_configs/openai_tiered_v1.json \\
        --workspace /tmp/checkpoint_l_gate1

Exit code: 0 on pass, non-zero on any assertion failure.

See ``docs/design/enable_loss_inventory.md`` § Checkpoint L for the full
gate definition + pass criteria.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agent.llm_bridge import LLMBridge
from agent.schemas.implementor import ImplementorInput
from agent.schemas.proposal import CustomLossSpec
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor
from workflows.task_config import get_task_description, load_task_config

# ---------------------------------------------------------------------------
# Hand-crafted CustomLossSpec — expected_value_mse
# ---------------------------------------------------------------------------
#
# Fully-differentiable ordinal-aware loss for [0, 256) ADC-bin classification.
# Mirrors what the proposer (Branch C of L5a's Rule 9) would emit when
# pointed at advice/workflow/checkpoint_l_loss_advice.json. No argmax, no
# .detach() — the implementor's dummy-tensor check should pass on the
# first attempt with very high probability.

EXPECTED_VALUE_MSE_SPEC = CustomLossSpec(
    loss_name="expected_value_mse",
    description=(
        "Expected-value MSE for ordinal ADC-bin classification. Standard "
        "cross-entropy treats the 256 output bins as independent "
        "categories, throwing away the fact that bin indices are an "
        "ordinal coordinate over a quantized continuous range. This loss "
        "computes the expected bin index under the model's softmax "
        "distribution and penalizes its squared distance to the target "
        "bin. Fully differentiable end-to-end; reduces gracefully toward "
        "regression as the distribution sharpens."
    ),
    mathematical_definition=(
        "Let logits = inputs [B, 256, T] float32 (requires_grad=True). "
        "Let y = targets [B, T] int64. "
        "Let idx = torch.arange(256, dtype=logits.dtype, device=logits.device) "
        ".view(1, 256, 1) [1, 256, 1]. "
        "Compute probs = F.softmax(logits, dim=1) [B, 256, T]. "
        "Compute soft_pred = (probs * idx).sum(dim=1) [B, T] (the expected "
        "bin index under the model's distribution). "
        "Compute se = (soft_pred - y.float()) ** 2 [B, T]. "
        "Return loss = se.mean() (scalar)."
    ),
    config_fields={},
)


# ---------------------------------------------------------------------------
# CLI + main
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    # ``__doc__`` is typed ``str | None`` even though it's literally set by
    # the module docstring above. Guard for pyright; fall back to a
    # reasonable description if some future tool strips docstrings.
    description = (__doc__ or "Checkpoint L Gate 1.").split("\n", 1)[0]
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--llm_config",
        required=True,
        help="Path to the LLM tier config (e.g. llm_configs/openai_tiered_v1.json).",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Workspace dir for the Gate 1 run. Loss file + capability index "
        "written here so the canonical agent_generated/_capability_index.json "
        "is not polluted.",
    )
    return parser.parse_args()


def _load_implementor_llm_cfg(llm_config_path: str) -> tuple[str, str]:
    """Read the implementor's (provider, model_id) from the tier-config JSON.

    Mirrors what the workflow does at workflows/model_exploration.py:1499 —
    ``MLModelImplementor(**llm_config.get("implement"))``.
    """
    with open(llm_config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    impl_cfg = cfg.get("implement")
    if not isinstance(impl_cfg, dict):
        raise ValueError(
            f"--llm_config {llm_config_path}: top-level 'implement' key must be "
            f"a dict with 'provider' and 'model_id'. Got: {impl_cfg!r}"
        )
    provider = impl_cfg.get("provider")
    model_id = impl_cfg.get("model_id")
    if not provider or not model_id:
        raise ValueError(
            f"--llm_config {llm_config_path}: 'implement' must include both "
            f"'provider' and 'model_id'. Got provider={provider!r}, model_id={model_id!r}."
        )
    return provider, model_id


def main() -> int:
    args = _parse_args()

    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    loss_dir = workspace / "losses"
    capability_index_path = str(workspace / "_capability_index.json")

    # Load task config so the implementor's system prompt receives the
    # task_description + forward_contract it expects in production.
    task_cfg = load_task_config()
    task_description = get_task_description(task_cfg)
    forward_contract = ForwardContract(**task_cfg["forward_contract"])

    provider, model_id = _load_implementor_llm_cfg(args.llm_config)

    print(f"=== Gate 1: generating loss '{EXPECTED_VALUE_MSE_SPEC.loss_name}' ===")
    print(f"  Workspace            : {workspace}")
    print(f"  Loss output dir      : {loss_dir}")
    print(f"  Capability index     : {capability_index_path}")
    print(f"  LLM provider         : {provider}")
    print(f"  LLM model_id         : {model_id}")
    print()

    # Construct the minimal ImplementorInput. The 4 required model-side
    # fields are filled with placeholders — _generate_loss only reads
    # custom_loss_spec, loss_dir, max_retries, storage, task_description,
    # and forward_contract. The model-side fields are present only because
    # the Pydantic schema requires them.
    inp = ImplementorInput(
        model_name="gate1_dummy",
        model_description="placeholder — Gate 1 exercises the loss path only",
        mathematical_definition="placeholder — Gate 1 does not generate a model",
        baseline_config={
            "model_config": {},
            "train_config": {},
            "loss_config": {
                "loss_type": "custom",
                "loss_name": EXPECTED_VALUE_MSE_SPEC.loss_name,
            },
        },
        task_description=task_description,
        forward_contract=forward_contract,
        loss_dir=str(loss_dir),
        max_retries=2,
        custom_loss_spec=EXPECTED_VALUE_MSE_SPEC,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(workspace), run_name="gate1"),
        ),
    )

    # Build the implementor with a REAL bridge.
    agent = MLModelImplementor(
        provider=provider,
        model_id=model_id,
        bridge_factory=LLMBridge,
        capability_index_path=capability_index_path,
    )

    # Run the loss-generation path only — does NOT call run() (which would
    # also try to generate a model).
    prov = agent._generate_loss(inp)

    print("\n=== LossProvenance ===")
    print(prov.model_dump_json(indent=2))

    # Print the generated source for visual inspection + the sign-off doc.
    print(f"\n=== Generated loss source (first 50 lines of {prov.loss_file_path}) ===")
    src_path = Path(prov.loss_file_path)
    if not src_path.is_file():
        print(f"ERROR: loss file does not exist at {prov.loss_file_path}", file=sys.stderr)
        return 2
    src_lines = src_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(src_lines[:50], 1):
        print(f"  {i:3d}: {line}")
    if len(src_lines) > 50:
        print(f"  ... ({len(src_lines) - 50} more lines)")

    # Inspect the registry write.
    entries = agent._registry.list(capability_type="loss")
    print(f"\n=== Capability registry — {len(entries)} loss entry/entries ===")
    for e in entries:
        print(e.model_dump_json(indent=2))

    # ---- Assertions ----
    # 1. Provenance shape
    assert prov.action == "generated", (
        f"Expected action='generated', got {prov.action!r}. "
        f"A 'reused' result here means the capability_index_path was wrong."
    )
    assert prov.loss_name == EXPECTED_VALUE_MSE_SPEC.loss_name, (
        f"Expected loss_name={EXPECTED_VALUE_MSE_SPEC.loss_name!r}, got {prov.loss_name!r}."
    )
    assert prov.dummy_tensor_validated is True, (
        "Expected dummy_tensor_validated=True; got False. The L4b validator "
        "rejected the generated source after all retries — inspect the chain "
        "log for the validation error."
    )

    # 2. File written
    assert os.path.isfile(prov.loss_file_path), f"Loss file missing on disk: {prov.loss_file_path}"

    # 3. Registry write
    assert len(entries) == 1, (
        f"Expected exactly 1 registry entry; got {len(entries)}. "
        f"Pre-existing entries indicate the capability_index_path was wrong."
    )
    entry = entries[0]
    assert entry.name == EXPECTED_VALUE_MSE_SPEC.loss_name
    assert entry.capability_type == "loss"
    assert entry.source_iteration == "gate1"
    assert entry.file_path == prov.loss_file_path

    print("\n=== Gate 1 PASSED ===")
    print(f"  Loss file       : {prov.loss_file_path}")
    print(f"  Registry entry  : {entry.name} (from {entry.source_iteration})")
    print("  Validated       : dummy-tensor pass on [B=2, 256, T=100] x [B=2, T=100]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
