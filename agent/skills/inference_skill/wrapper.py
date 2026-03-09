from core.sandbox_executor import TidmadSandbox

def run_skill(sandbox: TidmadSandbox, **kwargs):
    """
    Skill Wrapper for inference.
    """
    print(f"\n>>> [Skill: Inference] Running inference for {kwargs.get('exp_id')}...")
    
    return sandbox.execute_inference(
        exp_id=kwargs["exp_id"],
        run_name=kwargs["run_name"],
        model_type=kwargs["model_type"],
        m_cfg=kwargs["model_config"],
        l_cfg=kwargs["loss_config"]
    )