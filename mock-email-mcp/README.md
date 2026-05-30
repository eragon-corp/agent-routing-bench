# mock-email-mcp

A mock Gmail MCP server for benchmarking AI email agents. Exposes 10 Gmail-like tools (matching Composio's exact tool slugs and response schemas) backed by a local SQLite database.

## Tools

| Tool | Description |
|---|---|
| `GMAIL_FETCH_EMAILS` | Fetch/search emails with Gmail query syntax |
| `GMAIL_CREATE_EMAIL_DRAFT` | Create a draft |
| `GMAIL_DELETE_DRAFT` | Delete a draft by ID |
| `GMAIL_LIST_DRAFTS` | List all drafts |
| `GMAIL_SEND_EMAIL` | Send an email |
| `GMAIL_REPLY_TO_THREAD` | Reply to an existing thread |
| `GMAIL_ADD_LABEL_TO_EMAIL` | Add/remove labels on a message |
| `GMAIL_MOVE_THREAD_TO_TRASH` | Move a thread to trash |
| `GMAIL_LIST_LABELS` | List all Gmail labels |
| `GMAIL_GET_ATTACHMENT` | Retrieve an attachment |

## Install

fastmcp is already installed in the user site-packages for `/usr/bin/python3.10`.
No additional install step is required. If you need to reinstall:

```bash
pip install --user fastmcp>=2.0.0
```

## Seed the database

```bash
cd /var/lib/eragon-universal/benchmarking/mock-email-mcp
/usr/bin/python3.10 seed.py        # creates seed.db with 27 synthetic emails
/usr/bin/python3.10 reset.py       # copies seed.db → inbox.db
```

## Run the server

```bash
# Default: uses ./inbox.db in the current directory
MOCK_DB_PATH=/var/lib/eragon-universal/benchmarking/mock-email-mcp/inbox.db \
  /usr/bin/python3.10 /var/lib/eragon-universal/benchmarking/mock-email-mcp/server.py
```

The server communicates over **stdio** (standard MCP transport).

## Reset between runs

```bash
/usr/bin/python3.10 /var/lib/eragon-universal/benchmarking/mock-email-mcp/reset.py
```

This copies `seed.db` → `inbox.db`, restoring the original 27-email state.

## MCP configuration

### For Eragon / Claude Code

```json
{
  "mcpServers": {
    "mock-gmail": {
      "command": "/usr/bin/python3.10",
      "args": ["/var/lib/eragon-universal/benchmarking/mock-email-mcp/server.py"],
      "env": {
        "MOCK_DB_PATH": "/var/lib/eragon-universal/benchmarking/mock-email-mcp/inbox.db"
      }
    }
  }
}
```

## Database schema

- **messages** — email messages with label_ids as a JSON array
- **attachments** — binary attachment blobs linked to messages
- **drafts** — draft emails
- **labels** — Gmail system labels

## Seed data distribution

The 27 synthetic emails are distributed as:
- **10 unimportant**: newsletters, promos, cold SDR outreach, automated CI/CD/monitoring alerts
- **6 important_action** (INBOX+UNREAD+IMPORTANT): offer letter, invoice approval, legal doc signature, SOC2 questionnaire, VC interview scheduling, 2× suspicious password reset alerts
- **5 important_fyi** (INBOX): deployment status, Slack digest, AWS cost report, PR merged, standup notes
- **4 ambiguous** (INBOX+UNREAD): forwarded link with no context, vague follow-up, calendar invite from unknown, blank subject

Two emails have real attachment rows: an `.ics` calendar file and a `.pdf` offer letter.
