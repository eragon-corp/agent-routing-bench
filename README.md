# agent-routing-bench

Run harness and workflow skills for comparing routed and non-routed agent executions.

## Contents

```text
agent-routing-bench/
├── model-catalog.md
├── workflows/
│   ├── gmail-triage/
│   │   ├── skill.md
│   │   └── spec.md
│   ├── deep-research/
│   │   ├── skill.md
│   │   └── spec.md
│   └── soc2-auditor-comparison/
│       └── skill.md
├── harness/
│   ├── orchestrate.py
│   └── run-workflow.sh
└── mock-email-mcp/
```

## Run Methods

| Method ID | Description | Model(s) |
|---|---|---|
| `claude-code` | Claude Code CLI, single agent run | `claude` CLI |
| `eragon-norouting` | Eragon run with one pinned model for every step | `anthropic/claude-opus-4.8` via OpenRouter |
| `eragon-routing` | Eragon run using the skill routing table | Per routing table in `skill.md` |

## Running Workflows

Prerequisites:

- `hermes` CLI installed and on `$PATH`
- `claude` CLI installed and authenticated when using `claude-code`
- Python 3.10+
- MockMail configured when running the email triage workflow

Run all methods:

```bash
python3 harness/orchestrate.py deep-research
python3 harness/orchestrate.py gmail-triage
```

Run specific methods or fewer runs:

```bash
python3 harness/orchestrate.py deep-research --runs 3 --method eragon-routing
python3 harness/orchestrate.py gmail-triage --method eragon-norouting
```

## Run Artifacts

Each run creates:

```text
workflows/<name>/runs/run-NNN-<method>/
├── run.json
├── output.txt
└── timing.json
```

`runs/` is gitignored.

## Adding a Workflow

1. Create `workflows/<name>/`.
2. Add `skill.md`.
3. Add `spec.md` with the YAML metadata consumed by `harness/orchestrate.py`.
4. Run `python3 harness/orchestrate.py <name>`.

## License

MIT
