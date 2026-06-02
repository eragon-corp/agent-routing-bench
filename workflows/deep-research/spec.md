# Workflow Spec: deep-research

## Metadata

```yaml
workflow: deep-research
version: 1.0.0
requires_setup: false
parallelizable: true
parallel_reason: "Stateless workflow. Runs write to isolated run directories."
runs_per_method: 5
```

## Run Methods

| Method ID | Description | Model(s) | Routing Table Used? |
|---|---|---|---|
| `claude-code` | Claude Code CLI (`claude -p`) | Claude Code CLI | NO |
| `eragon-norouting` | Eragon run with one pinned model for every step | `anthropic/claude-opus-4.8` via `openrouter` provider | NO |
| `eragon-routing` | Eragon run using the per-step routing table from `skill.md` | Per routing table in `skill.md` | YES |

## Setup

`requires_setup: false`

No external account or shared mutable state is required. Each run writes to its own run directory.

## Parallelism

`parallelizable: true`

Runs may execute concurrently. The orchestrator limits concurrency with `MAX_PARALLEL_WORKERS`.
