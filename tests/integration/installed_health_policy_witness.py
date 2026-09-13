"""Manual offline Health witness for a wheel with its source checkout hidden.

Run under mount isolation with Python -I, a fresh external workspace and the
pre-change oracle. No training, model, provider or scientific-quality claim.
Independent bindings and damaged-resource probes each use a cold process.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _refuses(operation, expected, label):
    try:
        operation()
    except expected as error:
        return {"case": label, "error": type(error).__name__, "message": str(error)}
    raise AssertionError(f"{label} silently accepted")


def _scenario(args, baseline):
    import yaml
    from pydantic import ValidationError

    from execute_tools.health_checks._composition import HealthBindingState
    from execute_tools.health_checks.config import (
        default_health_policy_path,
        load_composed_health_config,
        load_health_gates_config,
        materialize_effective_config,
    )
    from execute_tools.health_checks.evaluation import evaluate_and_persist_health_gates
    from execute_tools.health_checks.launch_policy import validate_formal_launch
    from execute_tools.health_checks.schemas import HealthCheckContext

    root = args.workspace
    name = args.scenario
    if name.startswith("damaged_"):
        explicit = root.parent / "complete_explicit.yaml"
        # These imports already occurred with the asset damaged: no eager I/O.
        policy = load_health_gates_config(str(explicit)).resolved_policy()
        assert policy["blocking"].on_fail.value == "invalidate_round"
        failure = _refuses(load_health_gates_config, (OSError, ValidationError), name)
        return {"explicit_independent": True, "default_refusal": failure}

    expected = baseline["scenarios"][name]
    (root / "plugin.py").write_text(baseline["plugin"])
    task = root / "task.yaml"
    task.write_text(expected["task_yaml"])
    binding = HealthBindingState.EXPLICIT_NONE if name == "none" else str(task)
    policy_path = default_health_policy_path()
    policy = yaml.safe_load(Path(policy_path).read_text())
    source = None
    if name == "observe":
        policy["health_policy"]["blocking"]["on_fail"] = "continue"
        source = str(root / "observe.yaml")
        Path(source).write_text(yaml.safe_dump(policy))
    elif name in {"blank", "empty"}:
        source = str(root / "empty.yaml")
        Path(source).write_text("" if name == "blank" else "{}\n")
    elif name == "empty_path":
        source = ""

    effective, sha = materialize_effective_config(
        source, None, str(root / "effective"), task_health_binding=binding
    )
    content = Path(effective).read_text()
    body = "".join(line for line in content.splitlines(keepends=True) if not line.startswith("#"))
    assert body == expected["body"] and sha == expected["sha256"], name
    if not source:
        assert "# source: execute_tools/health_checks/resources/health_checks.yaml\n" in content
    assert materialize_effective_config(
        source, None, str(root / "effective"), task_health_binding=binding
    ) == (effective, sha)
    assert Path(effective).read_text() == content

    _, persisted, action = evaluate_and_persist_health_gates(
        HealthCheckContext(model_name="witness", run_name="baseline", round_index=1),
        config_path=effective,
        production_config_path=policy_path,
        task_health_binding=binding,
    )
    fields = {
        "gate_name",
        "gate_role",
        "check_passed",
        "resolved_action",
        "aggregation",
        "would_invalidate_under_production_policy",
        "execution_status",
        "check_verdicts",
    }
    assert [p.model_dump(mode="json", include=fields) for p in persisted] == expected["persisted"]
    assert action.value == expected["action"]
    validate_formal_launch(
        healthgate_mode="observe_only" if name in {"observe", "none"} else "blocking",
        result_authority="diagnostic",
        health_checks_config=effective,
        gates_enabled=False,
        skip_formal_min_delta=0.0,
        bypass_formal_time_budget_min_delta=0.5,
        task_health_binding=binding,
    )

    negatives = []
    if name == "default":
        equivalent = root / "equivalent_explicit.yaml"
        equivalent.write_text(yaml.safe_dump(policy))
        _, explicit_sha = materialize_effective_config(
            str(equivalent), None, str(root / "equivalent"), task_health_binding=binding
        )
        assert explicit_sha == sha
        assert (
            f"# source: {equivalent}\n"
            in (root / "equivalent/health_checks_effective.yaml").read_text()
        )
        for filename, text in (
            ("missing.yaml", None),
            ("malformed.yaml", "health_policy: ["),
            ("invalid.yaml", "health_policy: {blocking: {on_fail: unknown}}"),
        ):
            path = root / filename
            if text is not None:
                path.write_text(text)
            negatives.append(
                _refuses(
                    lambda path=path: load_composed_health_config(str(path), binding),
                    (OSError, yaml.YAMLError, ValidationError),
                    filename,
                )
            )
        for filename, text in (("missing_task.yaml", None), ("invalid_task.yaml", "roster: bad")):
            path = root / filename
            if text is not None:
                path.write_text(text)
            negatives.append(
                _refuses(
                    lambda path=path: load_composed_health_config(None, str(path)),
                    (OSError, ValueError),
                    filename,
                )
            )
        # A changed task threshold changes the body, never an existing workspace.
        task_body = yaml.safe_load(task.read_text())
        task_body["roster"][0]["parameters"]["threshold"] = 0.1
        task.write_text(yaml.safe_dump(task_body))
        negatives.append(
            _refuses(
                lambda: materialize_effective_config(
                    None, None, str(root / "effective"), task_health_binding=binding
                ),
                ValueError,
                "changed_body_resume",
            )
        )
        assert Path(effective).read_text() == content
        passing, _ = materialize_effective_config(
            None, None, str(root / "passing"), task_health_binding=binding
        )
        _, passing_results, passing_action = evaluate_and_persist_health_gates(
            HealthCheckContext(model_name="witness", run_name="pass", round_index=1),
            config_path=passing,
            production_config_path=policy_path,
            task_health_binding=binding,
        )
        assert passing_results[0].check_passed is True
        assert passing_results[1].check_passed is False
        assert passing_action.value == "continue"
    return {"sha256": sha, "action": action.value, "parity": True, "negatives": negatives}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--expected-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--unavailable-root", type=Path, action="append", default=[])
    parser.add_argument("--scenario")
    args = parser.parse_args()
    started = time.monotonic()
    assert "PYTHONPATH" not in os.environ
    args.workspace.mkdir(parents=True, exist_ok=False)
    from core.generated_library import bind_generated_library_to_workspace

    bind_generated_library_to_workspace(str(args.workspace))
    from core.layout import checkout_root
    from execute_tools.health_checks.config import default_health_policy_path

    assert checkout_root() is None
    import execute_tools.health_checks.config as config_module

    origin = Path(config_module.__file__).resolve()
    resource = Path(default_health_policy_path())
    assert origin.is_relative_to(args.expected_root)
    assert resource.is_relative_to(args.expected_root)
    origins = {}
    for name in (
        "agent",
        "nodes",
        "workflows",
        "core",
        "execute_tools",
        "ml_models",
        "dashboard",
        "tools",
    ):
        locations = list(importlib.import_module(name).__path__)
        assert locations and all(
            Path(p).resolve().is_relative_to(args.expected_root) for p in locations
        )
        origins[name] = locations
    for hidden in args.unavailable_root:
        assert not Path.cwd().is_relative_to(hidden)
        assert not (hidden / "CLAUDE.md").exists()
        assert not (hidden / "README.md").exists()
        assert not (hidden / "pyproject.toml").exists()
        assert not (hidden / "src/execute_tools/health_checks/config.py").exists()
        assert not (hidden / "configs/health/health_checks.yaml").exists()
        try:
            (hidden / "CLAUDE.md").read_text()
        except OSError:
            pass
        else:
            raise AssertionError(f"checkout remains readable: {hidden}")
    baseline = json.loads(args.baseline.read_text())
    if args.scenario:
        receipt = _scenario(args, baseline)
    else:
        assert args.unavailable_root, "physical checkout masking must be declared"
        results = {}

        def child(name):
            command = [
                sys.executable,
                "-I",
                __file__,
                "--workspace",
                str(args.workspace / name),
                "--expected-root",
                str(args.expected_root),
                "--baseline",
                str(args.baseline),
                "--scenario",
                name,
            ]
            for hidden in args.unavailable_root:
                command.extend(["--unavailable-root", str(hidden)])
            subprocess.run(command, check=True, timeout=30)
            return json.loads((args.workspace / name / "receipt.json").read_text())

        for name in baseline["scenarios"]:
            results[name] = child(name)
        original = resource.read_bytes()
        resource_sha = hashlib.sha256(original).hexdigest()
        # This is an explicitly selected independent override, not default rescue.
        (args.workspace / "complete_explicit.yaml").write_bytes(original)
        backup = resource.with_suffix(".witness-backup")
        assert not backup.exists()
        resource.rename(backup)
        try:
            results["damaged_missing"] = child("damaged_missing")
            resource.write_text("")
            results["damaged_blank"] = child("damaged_blank")
            resource.write_text("health_policy: {}\n")
            results["damaged_empty_policy"] = child("damaged_empty_policy")
        finally:
            backup.replace(resource)
        assert hashlib.sha256(resource.read_bytes()).hexdigest() == resource_sha
        receipt = {
            "results": results,
            "resource_sha256": resource_sha,
            "baseline_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        }
    receipt.update(
        {
            "interpreter": sys.executable,
            "module_origin": str(origin),
            "origins": origins,
            "resource": str(resource),
            "checkout": None,
            "hidden_roots": [str(p) for p in args.unavailable_root],
            "seconds": time.monotonic() - started,
        }
    )
    (args.workspace / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"PASS {args.scenario or 'installed Health witness'}")


if __name__ == "__main__":
    main()
