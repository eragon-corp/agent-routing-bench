# agent-routing-bench

A benchmarking harness for evaluating per-step LLM model routing in multi-agent workflows. Compares three strategies — Claude Cowork (no routing), Eragon all-Opus baseline, and Eragon with a cost-optimized routing table — across structured, multi-step agent workflows.

## What This Repo Contains

```
agent-routing-bench/
├── README.md                          # This file
├── .gitignore                         # Excludes runs/ and reports/ (data, not code)
├── model-catalog.md                   # 10-model catalog with pricing (source of truth for routing recommendations)
│
├── workflows/
│   ├── gmail-triage/
│   │   ├── skill.md                   # The gmail-triage skill v0.3.0 (6-step pipeline)
│   │   └── spec.md                    # Benchmark spec: methods, rubric, setup, judge instructions
│   │
│   └── deep-research/
│       ├── skill.md                   # The deep-research skill (7-step pipeline)
│       └── spec.md                    # Benchmark spec: methods, rubric, judge instructions
│
├── harness/
│   ├── orchestrate.py                 # Main orchestrator: creates runs, invokes run-workflow.sh, calls judge
│   ├── run-workflow.sh                # Shell script: runs a single workflow × method via hermes chat
│   └── judge.py                       # LLM judge: scores runs on D1–D4 rubric, writes reports
│
├── reports/                           # (gitignored) Generated benchmark reports
└── workflows/*/runs/                  # (gitignored) Per-run output, timing, and score files
```

## Benchmark Design

### Three Methods

| Method ID          | Description                                      | Model(s)                                      |
|--------------------|--------------------------------------------------|-----------------------------------------------|
| `claude-code`      | Claude Code CLI — no routing, single agent run   | `claude` CLI, authenticated via `claude auth login` |
| `eragon-norouting` | Eragon all-Opus — forces every step to Opus      | `anthropic/claude-opus-4-6` (all steps)       |
| `eragon-routing`   | Eragon with routing — per-step model routing     | Per routing table in `skill.md`               |

The `eragon-norouting` all-Opus run is the quality ceiling. Everything else is graded against it.

### Rubric: D1–D4 (1–5 per dimension, /20 per step)

| Code | Dimension          | What it tests                                                       |
|------|--------------------|---------------------------------------------------------------------|
| D1   | Correctness        | No hallucinated IDs, facts, URLs, or statistics                     |
| D2   | Completeness       | All required fields and content present; nothing silently dropped   |
| D3   | Format Adherence   | Exact JSON schema or markdown structure as specified                |
| D4   | Faithfulness       | Each step uses only its declared upstream inputs; no invented data  |

### Workflows

| Workflow        | Steps                                                            | Parallelizable | Setup Required |
|-----------------|------------------------------------------------------------------|----------------|----------------|
| `gmail-triage`  | fetch, classify, draft, plan, report, trash                      | NO             | YES (Gmail)    |
| `deep-research` | scope, search, extract, analyze, synthesize-report, synthesize-data, dashboard | YES | NO |

## Running Benchmarks

### Prerequisites

- `hermes` CLI installed and on `$PATH`
- For `gmail-triage`: Google Workspace OAuth connected to the Eragon gateway
- Python 3.10+ (standard library only — no extra dependencies)

### Run a full benchmark (5 runs × 3 methods)

```bash
cd /path/to/agent-routing-bench

# Deep research (parallel, no setup needed)
python3 harness/orchestrate.py deep-research

# Gmail triage (sequential, requires Gmail inbox setup)
python3 harness/orchestrate.py gmail-triage
```

### Run specific methods or fewer runs

```bash
# Only the routing method, 3 runs
python3 harness/orchestrate.py deep-research --runs 3 --method eragon-routing

# Only the all-Opus baseline, default 5 runs
python3 harness/orchestrate.py gmail-triage --method eragon-norouting
```

### Score a specific run manually

```bash
python3 harness/judge.py deep-research --run-id run-001-claude-code
```

### Generate/regenerate the aggregate report

```bash
python3 harness/judge.py deep-research
python3 harness/judge.py gmail-triage
```

Reports are written to `reports/<workflow>-report.md`.

## Report Format

Each generated report (`reports/<workflow>-report.md`) contains:

1. **Problem summary and context** — what the workflow does, what's being compared, how scoring works
2. **Summary of model output** — which method scored best overall
3. **Overall scores table** — method × average score per step and total
4. **Routing table recommendations** — which steps can be downgraded (based only on models in `model-catalog.md`)
5. **Appendix A1** — Full rubric (reproduced from spec.md)
6. **Appendix A2** — Full score breakdowns: D1–D4 per step per method per run, with judge evidence

## Adding a New Workflow

1. Create the workflow directory:
   ```bash
   mkdir -p workflows/<name>/runs/
   ```

2. Write the skill:
   - `workflows/<name>/skill.md` — the full skill document including routing table and step prompts

3. Write the spec:
   - `workflows/<name>/spec.md` — benchmark spec following the pattern of `gmail-triage/spec.md` or `deep-research/spec.md`
   - Required YAML front-matter fields: `requires_setup`, `parallelizable`, `steps_evaluated`, `runs_per_method`
   - Required sections: Methods, Rubric, Steps Evaluated, Judge Instructions (with JSON output format)

4. Run:
   ```bash
   python3 harness/orchestrate.py <name>
   ```

No harness code changes needed — the orchestrator reads the spec to determine parallelism and setup requirements automatically.

## Run Directory Structure

Each run creates:

```
workflows/<name>/runs/run-NNN-<method>/
├── run.json       # Metadata: run_id, method, workflow, timestamp, status
├── output.txt     # Full stdout from hermes chat invocation
├── timing.json    # Wall-clock timing and exit code
└── scores.json    # Judge scores (D1–D4 per step, written after judging)
```

`runs/` and `reports/` are gitignored — they are data artifacts, not code.

## Model Catalog

See `model-catalog.md` for the 10-model catalog including pricing per million tokens. Routing table recommendations in reports must use only model IDs from this catalog.

## License

MIT
