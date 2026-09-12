# `src/agent/skills/`

Atomic skill implementations. The seven wrapper directories are
[check_config_format](check_config_format_skill/README.md),
[denoising_score](denoising_score_skill/README.md),
[evaluate_time](evaluate_time_skill/README.md),
[evaluate_vram](evaluate_vram_skill/README.md),
[inference](inference_skill/README.md),
[paper_resolver](paper_resolver_skill/README.md), and
[training](training_skill/README.md). Each directory's `skill_config.json`
describes its exposed parameters; wrappers do not all share identical
signatures or effects. The flat modules [`forbidden_pattern_skill.py`](forbidden_pattern_skill.py)
and [`model_io_probe_skill.py`](model_io_probe_skill.py) are direct helpers,
not wrapper directories.

Effects are skill-specific: some inspect resources or launch subprocesses,
and paper resolution may use network access. Start with each child README and
[`test_skill_spec.py`](../../../tests/unit/agent/test_skill_spec.py) for the
declaration guard.
