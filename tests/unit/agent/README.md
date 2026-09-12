# Agent unit tests

These tests exercise typed agent boundaries with synthetic inputs, temporary workspaces, and mocked bridges; they do not prove provider access, real papers, GPU probing, or scientific training. Choose the child map matching the owner:

- [cache](cache/README.md) — consolidation, ranking, overflow, and bridge-call policy.
- [denoising_score_skill](denoising_score_skill/README.md), [training_skill](training_skill/README.md), [inference_skill](inference_skill/README.md) — estimator arithmetic and calibration seams.
- [evaluate_vram_skill](evaluate_vram_skill/README.md) — resource admission and probe decisions.
- [llm_bridge](llm_bridge/README.md) — one gateway, labels, timeout/retry, and usage records.
- [schemas](schemas/README.md) and [protocols](protocols/README.md) — cross-schema invariants and typed graph transport.
- [ml_literature_review](ml_literature_review/README.md), [ml_model_proposal_agent](ml_model_proposal_agent/README.md), [ml_model_implementor](ml_model_implementor/README.md), [ml_code_validator_agent](ml_code_validator_agent/README.md), [result_interpretation_agent](result_interpretation_agent/README.md), [tune_ml_hyperparam_agent](tune_ml_hyperparam_agent/README.md) — node contracts and orchestration.
- [prompt_templates](prompt_templates/README.md), [skills](skills/README.md), [utils](utils/README.md) — rendered prompts, adapters, and pure helpers.

Run the focused route named by a child guide. Opt-in integration/gate routes are outside this directory.
