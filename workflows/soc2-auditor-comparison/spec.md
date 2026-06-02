# Workflow Spec: soc2-auditor-comparison

## Metadata

```yaml
workflow: soc2-auditor-comparison
version: 1.0.0
requires_setup: true
parallelizable: false
parallel_reason: "Uses shared MockMail and Slack state. Run sequentially to keep inputs stable."
runs_per_method: 5
```

## Run Methods

| Method ID | Description | Model(s) | Routing Table Used? |
|---|---|---|---|
| `claude-code` | Claude Code CLI (`claude -p`) | Claude Code CLI | NO |
| `eragon-norouting` | Eragon run with one pinned model for every step | `anthropic/claude-opus-4.8` via `openrouter` provider | NO |
| `eragon-routing` | Eragon run using the per-step routing table from `skill.md` | Per routing table in `skill.md` | YES |

## Setup

This workflow expects:

- MockMail configured and seeded.
- Slack search tools available, or a graceful fallback if Slack is unavailable.

MockMail setup:

```bash
cd mock-email-mcp
python3.10 -m pip install -r requirements.txt -q
python3.10 seed.py
```

Reset before each run:

```bash
python3.10 reset.py
```

MCP configuration:

```json
{
  "mcpServers": {
    "mockmail": {
      "command": "python3.10",
      "args": ["/path/to/mock-email-mcp/server.py"],
      "env": { "MOCK_DB_PATH": "/path/to/mock-email-mcp/inbox.db" }
    }
  }
}
```

## Parallelism

`parallelizable: false`

Runs should be sequential because the workflow depends on shared communication data.
