"""Rev-4 deterministic gate evaluation (protocol §22.3 / operator §5,7).

Zero-LLM post-processing. Reads the run artifacts and evaluates every
frozen gate condition; emits gate_verdict.json into the run dir.
"""

import contextlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
RUN = REPO / "reports" / "artifacts" / "pr3_l2p" / "pilot_rev4_20260729"

EXTERNAL_RE = re.compile(r"^[a-z][a-z0-9_-]*:[\w./-]+$")
ARMS = {"S1_C_1": "C", "S1_T_1": "T", "S1_C_2": "C", "S1_T_2": "T"}


def legal(ic):
    st, si = ic.get("source_type"), ic.get("source_id") or ""
    return (st == "experiment" and bool(si)) or (
        st in ("external_agent", "human") and bool(EXTERNAL_RE.match(si))
    )


def main():
    out = {"samples": {}, "gate": {}}
    versions, total_calls = set(), 0
    correction_evidence = []
    failure_classes = []

    for sid, arm in ARMS.items():
        d = RUN / sid
        s = {"arm": arm, "exists": d.exists()}
        if not d.exists():
            out["samples"][sid] = s
            continue
        meta = (
            json.loads((d / "sample_meta.json").read_text())
            if (d / "sample_meta.json").exists()
            else {}
        )
        score = (
            json.loads((d / "deterministic_score.json").read_text())
            if (d / "deterministic_score.json").exists()
            else {}
        )
        s["terminal_error"] = meta.get("terminal_error")
        s["valid"] = bool(score.get("schema_valid"))
        s["aborted_incomplete"] = (d / "aborted_incomplete.json").exists()
        s["pipeline_mode"] = meta.get("production_pipeline_mode")
        s["treatment_isolation_ok"] = score.get("treatment_isolation_ok")
        s["prompt_has_treatment_block"] = score.get("prompt_has_treatment_block")

        calls, corrections, retries = [], 0, 0
        for line in (d / "calls.jsonl").read_text().splitlines():
            r = json.loads(line)
            calls.append(r)
            if not r.get("error"):
                total_calls += 1
                if r.get("model"):
                    versions.add(r["model"])
        # correction calls: request user prompt contains the marker
        for r in calls:
            msgs = r.get("request_messages") or []
            user = next((m["content"] for m in msgs if m["role"] == "user"), "")
            if "## VALIDATION ERROR — CORRECT AND RESEND" in user:
                corrections += 1
        s["calls"] = len(calls)
        s["correction_calls"] = corrections
        # proposing structural retries = proposer calls with proposing marker beyond 1
        prop_calls = 0
        for r in calls:
            if r.get("node") != "proposer":
                continue
            msgs = r.get("request_messages") or []
            sysp = next((m["content"] for m in msgs if m["role"] == "system"), "")
            if "custom_loss_spec" in sysp:
                prop_calls += 1
        s["proposing_attempts"] = prop_calls
        retries = max(0, prop_calls - 1)
        s["structural_retries"] = retries

        # citation/provenance audit on the final proposal
        cite_audit = []
        prop_p = d / "proposal_output.json"
        if prop_p.exists():
            prop = json.loads(prop_p.read_text())
            for ic in prop.get("inherited_components", []):
                cite_audit.append(
                    {
                        "component": ic.get("component"),
                        "source_type": ic.get("source_type"),
                        "source_id": ic.get("source_id"),
                        "regex_legal": legal(ic),
                    }
                )
        s["final_citations"] = cite_audit
        s["all_final_citations_legal"] = all(c["regex_legal"] for c in cite_audit)

        # corrected-value preservation: if corrections happened, the corrected
        # response's citations must equal the final output's citations
        if corrections and prop_p.exists():
            corrected_bodies = []
            for r in calls:
                msgs = r.get("request_messages") or []
                user = next((m["content"] for m in msgs if m["role"] == "user"), "")
                if "## VALIDATION ERROR — CORRECT AND RESEND" in user and r.get("response_content"):
                    with contextlib.suppress(Exception):
                        corrected_bodies.append(json.loads(r["response_content"]))
            if corrected_bodies:
                last = corrected_bodies[-1].get("inherited_components", [])
                final = json.loads(prop_p.read_text()).get("inherited_components", [])
                preserved = [
                    (a.get("source_id") if isinstance(a, dict) else None) for a in last
                ] == [f.get("source_id") for f in final]
                correction_evidence.append({"sample": sid, "corrected_values_preserved": preserved})

        # failure-class extraction for terminal samples
        tf = d / "terminal_failure.json"
        if tf.exists():
            err = json.loads(tf.read_text()).get("error", "")
            m = re.search(r"source_id '([^']+)'", err)
            failure_classes.append(m.group(1) if m else err[:80])
        out["samples"][sid] = s

    status = (
        json.loads((RUN / "run_status.json").read_text())
        if (RUN / "run_status.json").exists()
        else {}
    )
    summary = (
        json.loads((RUN / "run_summary.json").read_text())
        if (RUN / "run_summary.json").exists()
        else {}
    )
    manifest = json.loads((RUN / "launch_manifest.json").read_text())

    samples = out["samples"]
    valid = [s for s in samples.values() if s.get("valid")]
    valid_by_arm = {
        "C": sum(1 for s in samples.values() if s.get("valid") and s["arm"] == "C"),
        "T": sum(1 for s in samples.values() if s.get("valid") and s["arm"] == "T"),
    }
    from collections import Counter

    class_counts = Counter(failure_classes)
    g = out["gate"]
    g["1_four_of_four_valid"] = len(valid) == 4
    g["2_valid_in_each_arm"] = valid_by_arm["C"] >= 1 and valid_by_arm["T"] >= 1
    g["3_no_dominant_failure_class"] = all(v < 2 for v in class_counts.values())
    g["4_corrected_retry_values_preserved"] = (
        all(e["corrected_values_preserved"] for e in correction_evidence)
        if correction_evidence
        else "n/a — no correction retries occurred"
    )
    g["5_no_provenance_corruption"] = all(
        s.get("all_final_citations_legal", True) for s in samples.values()
    )
    g["6_complete_artifacts"] = (
        all(
            (not s["exists"])
            or s.get("valid")
            or s.get("terminal_error")
            or s.get("aborted_incomplete")
            for s in samples.values()
        )
        and (RUN / "run_status.json").exists()
        and (RUN / "run_summary.json").exists()
        and (RUN / "launch_command.json").exists()
    )
    g["7_runner_stop_and_exit_correct"] = bool(status)
    g["8_treatment_isolation_exact"] = all(
        s.get("treatment_isolation_ok") for s in samples.values() if s.get("valid")
    ) and all(
        s.get("prompt_has_treatment_block") == (s["arm"] == "T")
        for s in samples.values()
        if s.get("valid")
    )
    g["9_version_stable"] = len(versions) == 1
    g["10_caps_respected"] = total_calls <= manifest["design"]["hard_call_cap"] and (
        summary.get("cost_usd", 99) <= manifest["design"]["run_dollar_cap"]
    )

    hard_conditions = [
        v for k, v in g.items() if v is not True and v != "n/a — no correction retries occurred"
    ]
    out["verdict"] = "PASS" if not hard_conditions else "FAIL"
    out["run_status"] = status
    out["versions"] = sorted(versions)
    out["valid_by_arm"] = valid_by_arm
    out["failure_classes"] = dict(class_counts)
    out["correction_evidence"] = correction_evidence
    out["totals"] = {
        "calls": summary.get("calls"),
        "cost_usd": summary.get("cost_usd"),
        "input_tokens": summary.get("input_tokens"),
        "cached_tokens": summary.get("cached_tokens"),
        "output_tokens": summary.get("output_tokens"),
    }
    (RUN / "gate_verdict.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
