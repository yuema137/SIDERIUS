# skills/denoising_score_skill/wrapper.py

from core.sandbox_executor import TidmadSandbox


def run_skill(sandbox: TidmadSandbox, **kwargs):
    """
    Skill Wrapper for denoising score calculation.
    """
    print(f"\n>>> [Skill: Scoring] Calculating scores for {kwargs.get('exp_id')}...")

    return sandbox.execute_scoring(
        exp_id=kwargs["exp_id"],
        run_name=kwargs["run_name"],
        model_type=kwargs["model_type"],
        m_cfg=kwargs["model_config"],
        t_cfg=kwargs["train_config"],
        l_cfg=kwargs["loss_config"],
        # Step 12 / PR-12d D4b: the composed run's task-built scopes, already
        # in the tuner's `active_params` for the training and inference
        # spawns. Forwarded, not re-acquired — one acquisition, three children.
        task_scopes=kwargs.get("task_scopes"),
    )
