from core.sandbox_executor import TidmadSandbox

def run_skill(sandbox, **kwargs):
    print(f"\n>>> [Skill: Training] Initiating training for {kwargs.get('exp_id')}...")
    
    # align to skill_config.json and agent_main_pre.py
    return sandbox.execute_training(
        exp_id=kwargs["exp_id"],
        run_name=kwargs["run_name"],
        model_type=kwargs["model_type"],
        m_cfg=kwargs["model_config"],
        t_cfg=kwargs["train_config"], 
        l_cfg=kwargs["loss_config"]  
    )