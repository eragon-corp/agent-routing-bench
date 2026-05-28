#!/usr/bin/env python3
"""
judge.py — LLM judge for agent-routing-bench

Usage:
    python3 judge.py <workflow_name> [--run-id <specific_run>]

Examples:
    python3 judge.py deep-research
    python3 judge.py gmail-triage --run-id run-001-claude-code

Logic:
    1. Reads all completed runs from workflows/<name>/runs/ (or a specific run with --run-id).
    2. For each run, builds a judge prompt from spec.md + output.txt.
    3. Calls hermes chat with claude-opus-4-6 to score the run on D1–D4 per step.
    4. Saves scores.json in the run directory.
    5. When scoring all runs: aggregates per-method/per-step averages and writes
       reports/<workflow>-report.md in the required report format.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HARNESS_DIR = Path(__file__).parent.resolve()
REPO_ROOT   = HARNESS_DIR.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_file(path: Path) -> str:
    with open(path) as f:
        return f.read()


def call_hermes_judge(prompt: str) -> str:
    """
    Invoke hermes chat with claude-opus-4-6 as judge.
    Returns the raw stdout string.
    """
    result = subprocess.run(
        [
            "hermes", "chat",
            "-q", prompt,
            "-m", "anthropic/claude-opus-4-6",
            "--provider", "anthropic",
            "-Q",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        print(f"  [WARN] hermes judge exited {result.returncode}; stderr: {result.stderr[:200]}", file=sys.stderr)
    return result.stdout.strip()


def build_judge_prompt(spec_text: str, output_text: str, run_meta: dict) -> str:
    run_id  = run_meta.get("run_id", "unknown")
    method  = run_meta.get("method", "unknown")
    topic   = run_meta.get("topic", "")

    topic_line = f"\nResearch topic (if applicable): {topic}" if topic else ""

    return f"""You are an LLM judge evaluating the output of a benchmark run for an AI agent workflow.

Run metadata:
  run_id : {run_id}
  method : {method}{topic_line}

=== BENCHMARK SPEC (rubric + step definitions) ===
{spec_text}

=== RUN OUTPUT ===
{output_text}

=== JUDGE INSTRUCTIONS ===
Score every step listed in the spec rubric using dimensions D1, D2, D3, D4 (1–5 each).
For each dimension provide 1–2 sentences of evidence quoting specific output fragments.
Compute step total (D1+D2+D3+D4, max 20) and run total (sum of step totals).

Return ONLY valid JSON — no markdown fences, no prose before or after.
The JSON must follow exactly the output format specified in the spec's "Judge Instructions" section.
"""


def score_run(run_dir: Path, spec_text: str) -> dict | None:
    """
    Score a single run. Returns the parsed scores dict, or None on failure.
    Skips runs that are not completed, or already have scores.json.
    """
    run_json_path = run_dir / "run.json"
    output_path   = run_dir / "output.txt"
    scores_path   = run_dir / "scores.json"

    if not run_json_path.exists():
        return None

    with open(run_json_path) as f:
        run_meta = json.load(f)

    if run_meta.get("status") != "completed":
        print(f"  [SKIP] {run_dir.name} — status={run_meta.get('status')}")
        return None

    if not output_path.exists():
        print(f"  [SKIP] {run_dir.name} — output.txt missing")
        return None

    if scores_path.exists():
        print(f"  [CACHED] {run_dir.name} — scores.json already exists")
        with open(scores_path) as f:
            return json.load(f)

    print(f"  [JUDGE] {run_dir.name} ...", flush=True)
    output_text = read_file(output_path)
    prompt      = build_judge_prompt(spec_text, output_text, run_meta)
    raw_output  = call_hermes_judge(prompt)

    # Attempt JSON parse — strip any accidental fences
    json_str = raw_output
    if json_str.startswith("```"):
        lines = json_str.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        json_str = "\n".join(lines)

    try:
        scores = json.loads(json_str)
    except json.JSONDecodeError as exc:
        print(f"  [ERROR] {run_dir.name} — could not parse judge output as JSON: {exc}")
        print(f"          Raw output (first 500 chars): {raw_output[:500]}")
        return None

    # Persist scores
    with open(scores_path, "w") as f:
        json.dump(scores, f, indent=2)

    return scores


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_scores(all_scores: list[dict], workflow: str) -> dict:
    """
    Compute per-method × per-step averages.

    Returns:
    {
        method: {
            step: { "D1": avg, "D2": avg, "D3": avg, "D4": avg, "total": avg, "n": count },
            ...
            "_run_total": avg
        },
        ...
    }
    """
    # method → step → list of per-dimension values
    data: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    run_totals: dict[str, list[float]] = defaultdict(list)

    for s in all_scores:
        method = s.get("method", "unknown")
        step_scores = s.get("step_scores", {})
        run_total   = s.get("run_total")

        if run_total is not None:
            run_totals[method].append(float(run_total))

        for step, dims in step_scores.items():
            for dim in ("D1", "D2", "D3", "D4", "total"):
                if dim in dims:
                    data[method][step][dim].append(float(dims[dim]))

    result = {}
    for method, steps in data.items():
        result[method] = {}
        for step, dims in steps.items():
            result[method][step] = {}
            for dim, vals in dims.items():
                result[method][step][dim] = round(sum(vals) / len(vals), 2) if vals else None
            result[method][step]["n"] = len(dims.get("total", []))

        avg_run_total = (
            round(sum(run_totals[method]) / len(run_totals[method]), 2)
            if run_totals[method] else None
        )
        result[method]["_run_total"] = avg_run_total

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def method_display(method: str) -> str:
    return {
        "claude-code":      "Claude Code",
        "eragon-norouting": "Eragon No-Routing (all-Opus)",
        "eragon-routing":   "Eragon with Routing",
    }.get(method, method)


def read_model_catalog() -> str:
    catalog_path = REPO_ROOT / "model-catalog.md"
    if catalog_path.exists():
        return read_file(catalog_path)
    return "(model-catalog.md not found)"


def generate_report(workflow: str, all_scores: list[dict], agg: dict, spec_text: str) -> str:
    """Build the report markdown in the required format."""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    methods = sorted(agg.keys())

    # Determine step list from data
    all_steps: list[str] = []
    for m in methods:
        for k in agg[m]:
            if not k.startswith("_") and k not in all_steps:
                all_steps.append(k)

    # -----------------------------------------------------------------------
    # Section 1: Problem summary
    # -----------------------------------------------------------------------
    if workflow == "gmail-triage":
        problem_bullets = """\
- **Workflow:** gmail-triage v0.3.0 — 6-step Gmail inbox triage (fetch → classify → draft → plan → report → trash).
- **Goal:** Determine whether per-step model routing (mixing Opus, Sonnet, DeepSeek) preserves output quality vs. an all-Opus baseline, and measure the quality gap vs. Claude Cowork (no routing infrastructure).
- **Evaluation:** Each method scored on D1 Correctness, D2 Completeness, D3 Format Adherence, D4 Faithfulness (1–5 per dimension, /20 per step, /120 per run).
- **Constraint:** Runs are sequential (side-effectful Gmail writes); inbox restored between runs.
- **Key question:** Does the routing table's cost-optimized mix (−38% estimated cost) maintain ≥4/5 on all dimensions for every step?"""
    else:
        problem_bullets = """\
- **Workflow:** deep-research — 7-step research pipeline (scope → search → extract → analyze → synthesize-report → synthesize-data → dashboard).
- **Goal:** Determine whether per-step model routing preserves research quality (vs. all-Opus) while reducing cost, and measure quality vs. Claude Cowork (no routing).
- **Evaluation:** Each method scored on D1 Correctness, D2 Completeness, D3 Format Adherence, D4 Faithfulness (1–5 per dimension, /20 per step, /140 per run).
- **Parallelism:** All 15 runs (3 methods × 5 topics) executed concurrently (stateless workflow).
- **Key question:** Which steps can be safely downgraded to cheaper models without measurable quality loss?"""

    # -----------------------------------------------------------------------
    # Section 2: Summary of model output
    # -----------------------------------------------------------------------
    best_method = max(methods, key=lambda m: agg[m].get("_run_total") or 0) if methods else "N/A"
    best_score  = agg[best_method].get("_run_total") if methods else None

    output_bullets = f"""\
- Best overall average run score: **{method_display(best_method)}** with **{best_score}** average total.
- See the full score breakdown in Appendix A2 for per-step and per-run detail."""

    # -----------------------------------------------------------------------
    # Section 3: Overall scores table
    # -----------------------------------------------------------------------
    score_table_header = f"| Method | Avg Run Total | " + " | ".join(f"Avg {s}" for s in all_steps) + " |"
    score_table_sep    = "|--------|---------------|" + "|".join("---" for _ in all_steps) + "|"
    score_table_rows   = []
    for m in methods:
        row_parts = [method_display(m), str(agg[m].get("_run_total", "—"))]
        for step in all_steps:
            step_avg = agg[m].get(step, {}).get("total", "—")
            row_parts.append(str(step_avg))
        score_table_rows.append("| " + " | ".join(row_parts) + " |")

    score_table = "\n".join([score_table_header, score_table_sep] + score_table_rows)

    # -----------------------------------------------------------------------
    # Section 4: Routing table recommendations
    # -----------------------------------------------------------------------
    catalog = read_model_catalog()

    routing_recs = f"""\
Based on per-step averages above and the model catalog below, recommended routing adjustments:

*(Judge: populate this section after reviewing per-step scores. Use only model IDs from the catalog below.
For each step where `eragon-routing` scores within 0.5 of `eragon-norouting`, the routing table assignment
is validated. For steps where `eragon-routing` scores ≥0.5 below baseline, recommend upgrading that step
to a higher-quality model from the catalog.)*

### Model Catalog (source of truth for routing recommendations)

{catalog}"""

    # -----------------------------------------------------------------------
    # Appendix A1: Full rubric (extracted from spec)
    # -----------------------------------------------------------------------
    rubric_section = "*(See spec.md for full rubric — reproduced below.)*\n\n" + spec_text

    # -----------------------------------------------------------------------
    # Appendix A2: Full score breakdowns
    # -----------------------------------------------------------------------
    a2_parts = []
    for s in sorted(all_scores, key=lambda x: (x.get("method",""), x.get("run_id",""))):
        m       = s.get("method", "unknown")
        run_id  = s.get("run_id", "unknown")
        total   = s.get("run_total", "?")
        a2_parts.append(f"\n#### {run_id} ({method_display(m)}) — run total: {total}\n")
        step_scores = s.get("step_scores", {})
        if step_scores:
            a2_parts.append("| Step | D1 | D2 | D3 | D4 | Total |")
            a2_parts.append("|------|----|----|----|----|-------|")
            for step, dims in step_scores.items():
                d1    = dims.get("D1", "—")
                d2    = dims.get("D2", "—")
                d3    = dims.get("D3", "—")
                d4    = dims.get("D4", "—")
                t     = dims.get("total", "—")
                a2_parts.append(f"| {step} | {d1} | {d2} | {d3} | {d4} | {t} |")
            a2_parts.append("")

            # Evidence
            for step, dims in step_scores.items():
                ev = dims.get("evidence", {})
                if ev:
                    a2_parts.append(f"**{step} evidence:**")
                    for dim_name, text in ev.items():
                        a2_parts.append(f"- {dim_name}: {text}")
                    a2_parts.append("")

        judge_notes = s.get("judge_notes", "")
        if judge_notes:
            a2_parts.append(f"*Judge notes:* {judge_notes}\n")

    a2_content = "\n".join(a2_parts) if a2_parts else "*(No scored runs yet.)*"

    # -----------------------------------------------------------------------
    # Assemble report
    # -----------------------------------------------------------------------
    report = f"""# Benchmark Report: {workflow}

*Generated: {now}*

---

## 1. Problem Summary and Context

{problem_bullets}

---

## 2. Summary of Model Output

{output_bullets}

---

## 3. Overall Scores

{score_table}

---

## 4. Routing Table Recommendations

{routing_recs}

---

## Appendix A1: Full Rubric

{rubric_section}

---

## Appendix A2: Full Score Breakdowns

{a2_content}
"""
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="LLM judge for agent-routing-bench")
    parser.add_argument("workflow",               help="Workflow name (e.g., deep-research, gmail-triage)")
    parser.add_argument("--run-id", default=None, help="Score only this specific run ID")
    args = parser.parse_args()

    workflow = args.workflow
    run_id   = args.run_id

    # Validate workflow
    wf_dir = REPO_ROOT / "workflows" / workflow
    if not wf_dir.is_dir():
        sys.exit(f"ERROR: Workflow directory not found: {wf_dir}")

    spec_path = wf_dir / "spec.md"
    if not spec_path.exists():
        sys.exit(f"ERROR: spec.md not found at {spec_path}")

    spec_text = read_file(spec_path)
    runs_dir  = wf_dir / "runs"

    if not runs_dir.exists():
        sys.exit(f"ERROR: runs directory not found: {runs_dir}")

    # Collect run directories to score
    if run_id:
        target_dirs = [runs_dir / run_id]
        if not target_dirs[0].is_dir():
            sys.exit(f"ERROR: Run directory not found: {target_dirs[0]}")
    else:
        target_dirs = sorted(
            [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("run-")],
            key=lambda d: d.name,
        )

    if not target_dirs:
        print("No run directories found. Nothing to score.")
        return

    print(f"\nJudging {len(target_dirs)} run(s) for workflow '{workflow}' ...\n")

    all_scores: list[dict] = []
    for run_dir in target_dirs:
        scores = score_run(run_dir, spec_text)
        if scores:
            all_scores.append(scores)

    print(f"\nScored {len(all_scores)} / {len(target_dirs)} runs.")

    # If scoring all runs (no --run-id), generate aggregate report
    if not run_id and all_scores:
        print("\nAggregating scores and writing report ...", flush=True)
        agg = aggregate_scores(all_scores, workflow)

        reports_dir = REPO_ROOT / "reports"
        reports_dir.mkdir(exist_ok=True)
        report_path = reports_dir / f"{workflow}-report.md"

        report_md = generate_report(workflow, all_scores, agg, spec_text)
        with open(report_path, "w") as f:
            f.write(report_md)

        print(f"Report written to: {report_path}")

    elif not all_scores:
        print("No scores collected — report not generated.")


if __name__ == "__main__":
    main()
