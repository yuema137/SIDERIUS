# src/agent/skills/training_skill

This skill is entered through `wrapper.py::run_skill(sandbox, **kwargs)`; `skill_config.json` and `training_skill.md` define the callable contract and rendered description. The tuner’s private `execution.py` is the caller that supplies validated training inputs. Focused estimator tests cover forecast semantics; real training remains an explicit effectful path.

Validation/use route: follow the linked parent/module documentation and the focused tests for this directory; this guide is navigation, not a second API contract.
