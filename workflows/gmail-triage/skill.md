---
name: email-triage-multimodel
description: Triage an email inbox with per-step model routing — each phase runs as an isolated sessions_spawn subagent on a step-specific model. Routing table uses a cost-optimized mix: Opus for classify/draft, Sonnet for fetch/trash, and DeepSeek for plan/report.
version: 0.3.0
author: Eragon
license: MIT
metadata:
  eragon:
    tags: [email, triage, multimodel, routing]
    related_skills: [gog]
---

# Email Triage — Per-Step Model Routing

## Overview

End-to-end email triage workflow: fetch unread + actionable read mail, classify, draft replies (don't send), plan non-reply actions, report in 3 sections, auto-trash unimportant mail.

Each phase runs as **its own `sessions_spawn` subagent on a step-specific model with explicit context isolation**, so models can be swapped per row in the routing table without rewriting the skill. The current routing uses a cost-optimized mix: Opus 4.8 for high-judgment steps (classify, draft), Sonnet 4.6 for tool-call-heavy steps (fetch, trash), and DeepSeek V4 Pro for lightweight steps (plan, report).

## When to Use

- Any time you want each phase isolated in its own subagent with its own model (no shared context, no transcript bleed between phases).

Don't use for:
- Routine inbox triage where one model is fine — this multi-step routing workflow is slower than running the same workflow in one session.
- Composing one large reply from scratch — this skill is a triage workflow, not a writer.

## Model Routing Table

**Edit this table to change per-step models. Nothing else changes.** The orchestrator reads this table and passes `model=<model>` to each `sessions_spawn` call.

To list available model IDs, run `session_status` or check `/status` in chat.
Known compatible model IDs include `anthropic/claude-sonnet-4.6` for fetch/trash and `deepseek/deepseek-v4-pro` for plan/report.

| Step ID  | Phase             | Model                          | Provider    | Isolation   | Rationale                                                     |
|----------|-------------------|--------------------------------|-------------|-------------|---------------------------------------------------------------|
| fetch    | Phase 1: Fetch    | anthropic/claude-sonnet-4.6    | openrouter  | mode="run"  | Tool-call heavy but structured; Sonnet handles reliably.      |
| classify | Phase 2: Classify | anthropic/claude-opus-4.8      | openrouter  | mode="run"  | Nuanced judgment (important vs noise).                        |
| draft    | Phase 3: Draft    | anthropic/claude-opus-4.8      | openrouter  | mode="run"  | Tone-matching + thread context.                               |
| plan     | Phase 4: Plan     | deepseek/deepseek-v4-pro       | openrouter  | mode="run"  | Light reasoning; DeepSeek handles action plans at 6% cost.    |
| report   | Phase 5: Report   | deepseek/deepseek-v4-pro       | openrouter  | mode="run"  | Pure formatting; DeepSeek handles markdown assembly cheaply.  |
| trash    | Phase 6: Trash    | anthropic/claude-sonnet-4.6    | openrouter  | mode="run"  | Tool-call only, no reasoning; Sonnet is sufficient.           |

**Why `mode="run"` on every step:** In Eragon, `mode="run"` subagents are one-shot and do NOT inherit the parent session's transcript — they are context-isolated by design. Each child only receives the structured upstream output the orchestrator passes through the `task` string. No child needs or gets the parent transcript.

**Context isolation per step:**
- `fetch` — no upstream input
- `classify` — needs `fetch.output` only (passed in `task`)
- `draft` — needs `fetch.output` + `classify.output` (passed in `task`)
- `plan` — needs `fetch.output` + `classify.output` + `draft.output` (passed in `task`)
- `report` — needs all four upstream outputs (passed in `task`)
- `trash` — needs only the `unimportant` ID list from `classify.output` (passed in `task`)

## Routing Protocol (orchestrator must follow exactly)

1. Treat the routing table as the **single source of truth** for `model` per `step_id`.
2. For each step in order (fetch → classify → draft → plan → report → trash):
   - Build the per-step prompt from the "Steps" section below, substituting `{{prior_step.output}}` placeholders with the captured output of earlier steps.
   - Record wall-clock start time.
   - Spawn the subagent:
     ```
     sessions_spawn(
         task      = <FULL_STEP_PROMPT>,
         model     = <MODEL_FROM_ROUTING_TABLE>,
         mode      = "run",
         runtime   = "subagent",
         runTimeoutSeconds = 600,
         cleanup   = "keep",
         label     = "triage-<step_id>",
     )
     ```
   - Record wall-clock elapsed time after completion.
   - Capture the subagent's reply as `{{<step_id>.output}}`.
   - Save the captured output to a per-step file before continuing, so intermediate work is available for inspection and reruns.

3. **Verify model routing after every spawn.** After each `sessions_spawn` completes, check two things:

   **(a) Check `modelApplied` in the spawn result.**
   Eragon returns `modelApplied: true` when the model override was applied successfully. If `modelApplied` is `false` or missing when a model was requested, abort — the child ran on the default model, not the routing table's model.

   **(b) Check the `MODEL_USED:` line in the child's output.**
   Every step prompt begins with a `ROUTING_VERIFY` instruction that asks the child to echo its model ID as the first line. After capturing output, verify the first line matches `MODEL_USED:<expected_model>`. If it doesn't match or is missing, abort.

   **Both checks must pass.** `modelApplied` catches Eragon-level fallback; `MODEL_USED:` catches model self-reporting errors.

   If either check fails: **abort the entire run**, report which step failed, and do NOT retry on a different model.

4. If any step errors, times out (`runTimeoutSeconds=600`), or fails model verification, abort the whole run. Report which step + which model + the failure reason.

## MockMail MCP Server

Email access is provided by **MockMail** — a local MCP server backed by a SQLite inbox snapshot. Tools are prefixed `MOCKMAIL_` (e.g. `MOCKMAIL_FETCH_EMAILS`, `MOCKMAIL_CREATE_EMAIL_DRAFT`). MockMail exposes Gmail-like tool schemas and Gmail-style search syntax, but this workflow should otherwise treat the source as generic email.

**Setup (one-time):**
```bash
cd /path/to/agent-routing-bench/mock-email-mcp
python3.10 -m pip install -r requirements.txt -q
python3.10 seed.py   # creates seed.db from fixtures/seed_emails.json
python3.10 reset.py  # copies seed.db → inbox.db (ready to run)
```

**Reset before each run** (restores inbox to seed state, instant):
```bash
python3.10 reset.py
```

**MCP config** (add to Hermes config or Claude Code config):
```json
{
  "mcpServers": {
    "mockmail": {
      "command": "python3.10",
      "args": ["/path/to/agent-routing-bench/mock-email-mcp/server.py"],
      "env": { "MOCK_DB_PATH": "/path/to/agent-routing-bench/mock-email-mcp/inbox.db" }
    }
  }
}
```

The inbox contains 114 emails (25 unread) seeded from a real inbox. Company names, amounts, URLs, and thread structure are verbatim; colleague/client names are anonymized.

## Inputs

Single optional arg passed in the orchestrator's user message:
- `max_emails` (default 100): cap on emails pulled in Phase 1.

## Shared Preamble (prepend to every step prompt)

```
ROUTING_VERIFY: Echo the first line of your response as: MODEL_USED:<your model id>

You are running as one isolated step of an email triage workflow.

Rules:
- Never auto-send email. Drafts only. Trashing is allowed (recoverable 30d).
- When in doubt about classification, prefer "important_fyi" over "unimportant".
- Return your output as plain text or JSON only — no preamble after MODEL_USED, no sign-off, no markdown fences unless explicitly asked.
- Use MockMail MCP tools for all email access and mutation.
```

---

## Steps

### Step `fetch` — Phase 1: Fetch candidate emails

**Upstream input:** none.

Full prompt to subagent (after shared preamble):

```
Task: fetch candidate inbox emails for triage.

1. Fetch unread inbox messages (paginate if nextPageToken present):
   MOCKMAIL_FETCH_EMAILS(max_results=50, query="is:unread in:inbox", fetch_full_message=false)

2. Fetch recent read actionable messages:
   MOCKMAIL_FETCH_EMAILS(max_results=50, query="is:read in:inbox newer_than:14d", fetch_full_message=false)

3. The fetch tool returns the message fields needed for triage. Deduplicate by threadId.

4. Cap total at {{max_emails}}.

5. For each surviving message extract: id, threadId, from, subject, snippet, internalDate, labelIds.

Note: MockMail supports Gmail-style query syntax. If the response has a nextPageToken, fetch the next page using next_page_token=<token>
until exhausted or cap is reached. Note "TRUNCATED:Y" if you hit the cap.

Return JSON only (no fences):
{
  "emails": [
    {"id":"...","threadId":"...","from":"...","subject":"...","snippet":"...","internalDate":"...","labelIds":[...]},
    ...
  ],
  "truncated": true|false,
  "total_fetched": <N>
}
```

Output capture: `{{fetch.output}}` — JSON string.

---

### Step `classify` — Phase 2: Categorize

**Upstream input:** `{{fetch.output}}` (email JSON).

Full prompt to subagent (after shared preamble):

```
Task: classify each email into one of three buckets.

Input (JSON):
{{fetch.output}}

Buckets:
- important_action — direct ask, deadline, known person, financial/legal/health, work threads with question or @mention
- important_fyi    — paid newsletters, confirmations, receipts, accepted invites
- unimportant      — promos, marketing, cold outreach, expired notifications, social digests

Heuristics: sender domain reputation, subject keywords ("action required","?","by Friday","invoice"),
body length + question marks + direct address, prior thread history in labelIds.

Rule: borderline → important_fyi (never unimportant).

Return JSON only (no fences):
{
  "important_action": ["<id>", ...],
  "important_fyi":    ["<id>", ...],
  "unimportant":      ["<id>", ...],
  "rationale_by_id":  {"<id>": "<one-line reason>", ...}
}
```

Output capture: `{{classify.output}}` — JSON string.

---

### Step `draft` — Phase 3: Draft replies (no send)

**Upstream input:** `{{fetch.output}}` + `{{classify.output}}`.

Full prompt to subagent (after shared preamble):

```
Task: write reply drafts for important_action emails that need a response. DO NOT SEND.

Inputs (JSON):
emails:         {{fetch.output}}
classification: {{classify.output}}

For each id in classification.important_action where the last message is FROM someone else and expects a reply:

1. Compose a concise reply: direct, no filler, no "Hope you're well".
   Insert [CONFIRM:<fact>] wherever a fact isn't grounded in the email thread.

2. Create the draft with MockMail:
   MOCKMAIL_CREATE_EMAIL_DRAFT(recipient_email="<to>", subject="Re: <subject>", body="<body>")

3. Capture the returned draft id from the response.

Return JSON only (no fences):
{
  "drafts": [
    {"email_id":"...","draft_id":"...","to":"...","subject":"...","one_line_summary":"..."},
    ...
  ],
  "skipped": [
    {"email_id":"...","reason":"no reply needed"},
    ...
  ]
}
```

Output capture: `{{draft.output}}` — JSON string.

---

### Step `plan` — Phase 4: Non-reply action plans

**Upstream input:** `{{fetch.output}}` + `{{classify.output}}` + `{{draft.output}}`.

Full prompt to subagent (after shared preamble):

```
Task: for each important_action email that does NOT need a reply (e.g. "pay invoice", "review doc",
"book flight"), write a one-line action plan.

Inputs:
emails:         {{fetch.output}}
classification: {{classify.output}}
drafts:         {{draft.output}}

For each id in classification.important_action that is NOT in drafts.drafts[].email_id:
  Produce: {"email_id":"...","what":"...","when":"<deadline or 'no deadline'>","where":"<link or location or 'n/a'>"}

Return JSON only (no fences):
{
  "actions": [
    {"email_id":"...","what":"...","when":"...","where":"..."},
    ...
  ]
}
```

Output capture: `{{plan.output}}` — JSON string.

---

### Step `report` — Phase 5: 3-section summary

**Upstream input:** `{{fetch.output}}` + `{{classify.output}}` + `{{draft.output}}` + `{{plan.output}}`.

Full prompt to subagent (after shared preamble):

```
Task: format the final triage report.

Inputs:
emails:         {{fetch.output}}
classification: {{classify.output}}
drafts:         {{draft.output}}
plan:           {{plan.output}}

Output markdown with these exact sections (no fences, no preamble after MODEL_USED):

# Inbox Triage — Summary

## 1. Required Responses (<N> drafts written)
- From: <from> — "<Subject>"
  Draft: "<one_line_summary>" [Draft ID: <draft_id>]

## 2. Actions Required (<N> items, no reply)
- <what> — <when> — <where>

## 3. FYI / Pending Review
- <from> — "<subject>" (<one-line why it's fyi>)

**Unimportant emails queued for trash: <count of classification.unimportant>**
```

Output capture: `{{report.output}}` — markdown string.

---

### Step `trash` — Phase 6: Auto-trash unimportant (no confirm)

**Upstream input:** `{{classify.output}}` (only the `unimportant` ID list).

Full prompt to subagent (after shared preamble):

```
Task: move every email in classification.unimportant to Trash. Auto, no confirm.
Trash only — never permanent delete.

Inputs:
classification: {{classify.output}}

For each id in classification.unimportant:
  Find the corresponding threadId from the fetched email data and call:
  MOCKMAIL_MOVE_THREAD_TO_TRASH(thread_id="<threadId>")

Capture the result of each call. If the call returns a non-200 status or an "error" field,
record it in failed[].

Return JSON only (no fences):
{
  "trashed": ["<id>", ...],
  "failed":  [{"id":"...","error":"..."}, ...],
  "top_senders": ["<top 5 sender addresses from trashed batch>"]
}
```

Output capture: `{{trash.output}}` — JSON string.

---

## Final Orchestrator Output

After all 6 steps succeed, the orchestrator's reply is:

1. `{{report.output}}` verbatim (the markdown summary).
2. A trailing line:
   `**Trashed: <N> unimportant emails** (recoverable 30 days). Top senders: <comma-separated from {{trash.output}}.top_senders>`
3. A **Routing Audit** footer built from real values captured during the run:

```
---
## Routing Audit
| step     | model                     | modelApplied | model_verified | exit_status | wallclock_s |
|----------|---------------------------|--------------|----------------|-------------|-------------|
| fetch    | anthropic/claude-sonnet-4.6  | ✅           | ✅             | completed   | 12.4        |
| classify | anthropic/claude-opus-4.8    | ✅           | ✅             | completed   | 18.1        |
| draft    | anthropic/claude-opus-4.8    | ✅           | ✅             | completed   | 34.7        |
| plan     | deepseek/deepseek-v4-pro     | ✅           | ✅             | completed   | 6.3         |
| report   | deepseek/deepseek-v4-pro     | ✅           | ✅             | completed   | 4.9         |
| trash    | anthropic/claude-sonnet-4.6  | ✅           | ✅             | completed   | 9.0         |
```

Column definitions:
- **model** — the model ID from the routing table that was passed to `sessions_spawn`
- **modelApplied** — ✅ if `sessions_spawn` returned `modelApplied: true`, ❌ otherwise
- **model_verified** — ✅ if the child's first output line was `MODEL_USED:<expected_model>`, ❌ otherwise
- **exit_status** — `completed` / `error` / `timeout` from the subagent completion event
- **wallclock_s** — orchestrator-measured wall-clock seconds for the spawn

Keep this audit with the run output for troubleshooting and reproducibility.

---

## Verification Checklist

- [ ] Every `sessions_spawn` call passes `model` from the routing table (not inherited, not hardcoded inline).
- [ ] Every `sessions_spawn` call uses `mode="run"` (context-isolated by design).
- [ ] After each spawn, `modelApplied` is checked — `false` aborts the run.
- [ ] After each spawn, the child's first output line `MODEL_USED:<model>` is verified against the routing table — mismatch aborts the run.
- [ ] No step retries on a different model after failure.
- [ ] Routing Audit footer is appended to the final reply with one row per phase.
- [ ] All 6 subagents completed without error.
- [ ] `{{report.output}}` has the 3 required sections.
- [ ] Number of drafts in Phase 3 ≤ number of `important_action` emails in Phase 2.
- [ ] Number trashed in Phase 6 = number of `unimportant` emails in Phase 2.
- [ ] No email was sent (only drafts created via `MOCKMAIL_CREATE_EMAIL_DRAFT`).
- [ ] No permanent deletes — trash only, never delete.
