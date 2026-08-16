def run_skill(sandbox, **kwargs):
    print(f"\n>>> [Skill: Training] Initiating training for {kwargs.get('exp_id')}...")

    # align to skill_config.json and agent_main_pre.py
    return sandbox.execute_training(
        exp_id=kwargs["exp_id"],
        run_name=kwargs["run_name"],
        model_type=kwargs["model_type"],
        m_cfg=kwargs["model_config"],
        t_cfg=kwargs["train_config"],
        l_cfg=kwargs["loss_config"],
        sample_set=kwargs.get("sample_set"),
        # Step 07a: the tuner's EXISTING run-bound eval SampleSet reaches the
        # trainer (R3 validation pass) — before 07a this kwarg was enumerated
        # away right here, the transport-drop defect OD-S7-1 names. The
        # tuner boundary decides `expected_validation` from the same value,
        # so re-dropping it can no longer produce a quiet success.
        eval_sample_set=kwargs.get("eval_sample_set"),
        train_portion=kwargs.get("train_portion"),
        train_base_seed=kwargs.get("train_base_seed"),
        # RT2-G: operator runtime policy for in-subprocess verification
        # (validated against RuntimeControlPolicy at the executor).
        runtime_policy=kwargs.get("runtime_policy"),
        # V19 PR 2: RESOLVED ordering. The resolver already combined the
        # agent proposal with any operator override upstream; nothing below
        # this point re-derives precedence.
        order_strategy=kwargs.get("order_strategy", "shuffle"),
        file_order=kwargs.get("file_order"),
    )
