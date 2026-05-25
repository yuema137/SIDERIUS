from core.sandbox_executor import TidmadSandbox


def run_skill(sandbox: TidmadSandbox, **kwargs):
    """Skill Wrapper for inference.

    Phase 6.6 A.11: ``inference_batch`` is forwarded from the tuner's
    ``active_params`` dict (seeded by the ``evaluate_vram_skill`` result).
    When absent, ``execute_inference`` falls back to the legacy registry
    via ``inference_batch_for(model_type)`` — preserves back-compat during
    the A.7 landing window and is removed in A.9.
    """
    print(f"\n>>> [Skill: Inference] Running inference for {kwargs.get('exp_id')}...")

    return sandbox.execute_inference(
        exp_id=kwargs["exp_id"],
        run_name=kwargs["run_name"],
        model_type=kwargs["model_type"],
        m_cfg=kwargs["model_config"],
        l_cfg=kwargs["loss_config"],
        sample_set=kwargs.get("eval_sample_set"),
        inference_batch=kwargs.get("inference_batch"),
    )
