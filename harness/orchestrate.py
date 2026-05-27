#!/usr/bin/env python3
"""
orchestrate.py — Benchmarking orchestrator for agent-routing-bench

Usage:
    python3 orchestrate.py <workflow_name> [--runs 5] [--method all|cowork|eragon-norouting|eragon-routing]

Examples:
    python3 orchestrate.py deep-research
    python3 orchestrate.py deep-research --runs 3 --method eragon-routing
    python3 orchestrate.py gmail-triage --runs 5 --method all
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

METHODS = ["cowork", "eragon-norouting", "eragon-routing"]
MAX_PARALLEL_WORKERS = 5

# Resolve paths relative to the repo root (parent of harness/)
HARNESS_DIR = Path(__file__).parent.resolve()
REPO_ROOT   = HARNESS_DIR.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_spec(workflow: str) -> dict:
    """Parse key flags from workflows/<workflow>/spec.md front-matter block."""
    spec_path = REPO_ROOT / "workflows" / workflow / "spec.md"
    if not spec_path.exists():
        sys.exit(f"ERROR: spec.md not found at {spec_path}")

    flags = {
        "requires_setup": False,
        "parallelizable": True,
    }

    in_yaml = False
    with open(spec_path) as f:
        for line in f:
            stripped = line.strip()
            if stripped == "```yaml":
                in_yaml = True
                continue
            if in_yaml and stripped == "```":
                break
            if in_yaml:
                if stripped.startswith("requires_setup:"):
                    val = stripped.split(":", 1)[1].strip().lower()
                    flags["requires_setup"] = val == "true"
                elif stripped.startswith("parallelizable:"):
                    val = stripped.split(":", 1)[1].strip().lower()
                    flags["parallelizable"] = val == "true"

    return flags


def next_run_number(runs_dir: Path) -> int:
    """Return the next sequential run number (1-indexed) based on existing run dirs."""
    existing = [
        d for d in runs_dir.iterdir()
        if d.is_dir() and d.name.startswith("run-")
    ] if runs_dir.exists() else []
    if not existing:
        return 1
    nums = []
    for d in existing:
        parts = d.name.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            nums.append(int(parts[1]))
    return (max(nums) + 1) if nums else 1


def create_run_dir(workflow: str, run_number: int, method: str) -> Path:
    """Create the run directory and write run.json metadata. Returns the run dir path."""
    runs_dir  = REPO_ROOT / "workflows" / workflow / "runs"
    run_id    = f"run-{run_number:03d}-{method}"
    run_dir   = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "run_id":    run_id,
        "method":    method,
        "workflow":  workflow,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status":    "pending",
    }
    with open(run_dir / "run.json", "w") as f:
        json.dump(run_meta, f, indent=2)

    return run_dir


def execute_run(workflow: str, method: str, run_dir: Path) -> dict:
    """
    Call harness/run-workflow.sh and return a result dict.
    Updates run.json with final status.
    """
    run_id     = run_dir.name
    script     = HARNESS_DIR / "run-workflow.sh"
    run_json   = run_dir / "run.json"

    print(f"  [START] {run_id}", flush=True)

    try:
        result = subprocess.run(
            ["bash", str(script), workflow, method, run_id],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        success = result.returncode == 0
    except Exception as exc:
        success = False
        result  = None
        print(f"  [ERROR] {run_id}: subprocess exception: {exc}", flush=True)

    # Update run.json status
    with open(run_json) as f:
        meta = json.load(f)
    meta["status"] = "completed" if success else "failed"
    with open(run_json, "w") as f:
        json.dump(meta, f, indent=2)

    status_label = "OK" if success else "FAIL"
    print(f"  [{status_label}]   {run_id}", flush=True)

    return {
        "run_id":   run_id,
        "method":   method,
        "run_dir":  str(run_dir),
        "success":  success,
        "returncode": result.returncode if result else -1,
    }


def run_judge(workflow: str) -> None:
    """Invoke harness/judge.py to score all completed runs."""
    judge_script = HARNESS_DIR / "judge.py"
    print(f"\n[JUDGE] Scoring all completed runs for '{workflow}' ...", flush=True)
    subprocess.run(
        [sys.executable, str(judge_script), workflow],
        cwd=str(REPO_ROOT),
        check=False,
    )


def print_summary(results: list[dict]) -> None:
    """Print a summary table of run outcomes."""
    print("\n" + "=" * 60)
    print("BENCHMARK RUN SUMMARY")
    print("=" * 60)

    # Group by method
    by_method: dict[str, list[dict]] = {}
    for r in results:
        by_method.setdefault(r["method"], []).append(r)

    col_w = max(len(m) for m in by_method) if by_method else 20
    header = f"  {'Method':<{col_w}}  Runs  OK   Failed"
    print(header)
    print("  " + "-" * (len(header) - 2))

    total_ok = 0
    total_fail = 0
    for method, runs in sorted(by_method.items()):
        ok     = sum(1 for r in runs if r["success"])
        failed = len(runs) - ok
        total_ok   += ok
        total_fail += failed
        print(f"  {method:<{col_w}}  {len(runs):<5} {ok:<4} {failed}")

    print("  " + "-" * (len(header) - 2))
    print(f"  {'TOTAL':<{col_w}}  {len(results):<5} {total_ok:<4} {total_fail}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orchestrate benchmarking runs for a given workflow."
    )
    parser.add_argument("workflow",          help="Workflow name (e.g., deep-research, gmail-triage)")
    parser.add_argument("--runs",   type=int, default=5,   help="Number of runs per method (default: 5)")
    parser.add_argument(
        "--method",
        default="all",
        choices=["all"] + METHODS,
        help="Which method(s) to run (default: all)",
    )
    args = parser.parse_args()

    workflow = args.workflow
    n_runs   = args.runs
    methods  = METHODS if args.method == "all" else [args.method]

    # Validate workflow exists
    wf_dir = REPO_ROOT / "workflows" / workflow
    if not wf_dir.is_dir():
        sys.exit(f"ERROR: Workflow directory not found: {wf_dir}")

    # Read spec flags
    spec = read_spec(workflow)
    requires_setup  = spec["requires_setup"]
    parallelizable  = spec["parallelizable"]

    print(f"\nBenchmark: {workflow}")
    print(f"  Methods  : {', '.join(methods)}")
    print(f"  Runs each: {n_runs}")
    print(f"  Parallel : {parallelizable}")
    print(f"  Setup req: {requires_setup}")
    print()

    # Build the full list of (run_number, method) pairs to execute
    runs_dir    = REPO_ROOT / "workflows" / workflow / "runs"
    start_num   = next_run_number(runs_dir)
    run_configs = []

    for i, method in enumerate(methods):
        for j in range(n_runs):
            run_num = start_num + i * n_runs + j
            run_configs.append((run_num, method))

    # Create all run directories up front (sequential, safe for parallelism)
    run_dirs: dict[tuple[int, str], Path] = {}
    for run_num, method in run_configs:
        run_dirs[(run_num, method)] = create_run_dir(workflow, run_num, method)

    # Execute runs
    results: list[dict] = []

    if parallelizable and not requires_setup:
        # Parallel execution
        print(f"Running {len(run_configs)} tasks in parallel (max {MAX_PARALLEL_WORKERS} workers) ...\n")
        futures_map = {}
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
            for run_num, method in run_configs:
                run_dir = run_dirs[(run_num, method)]
                future  = executor.submit(execute_run, workflow, method, run_dir)
                futures_map[future] = (run_num, method)

            for future in as_completed(futures_map):
                try:
                    results.append(future.result())
                except Exception as exc:
                    run_num, method = futures_map[future]
                    print(f"  [ERROR] run-{run_num:03d}-{method}: {exc}", flush=True)
    else:
        # Sequential execution
        print(f"Running {len(run_configs)} tasks sequentially ...\n")
        for run_num, method in run_configs:
            run_dir = run_dirs[(run_num, method)]
            result  = execute_run(workflow, method, run_dir)
            results.append(result)

    # Print summary before judging
    print_summary(results)

    # Run judge
    completed = [r for r in results if r["success"]]
    if completed:
        run_judge(workflow)
    else:
        print("\n[JUDGE] Skipped — no successful runs to score.")

    print("\nDone.")


if __name__ == "__main__":
    main()
