# src/agent/skills/training_skill

This skill is entered through `wrapper.py::run_skill(sandbox, **kwargs)`; `skill_config.json` and `training_skill.md` define the callable contract and rendered description. The tuner’s private `execution.py` is the caller that supplies validated training inputs. Focused estimator tests cover forecast semantics; real training remains an explicit effectful path.

See [the parent guide](../README.md) for child ownership and the focused validation route.
