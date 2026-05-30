---
name: gmail-triage-multimodel
description: Triage Gmail inbox with per-step model routing — each phase runs as an isolated sessions_spawn subagent on a step-specific model. Routing table uses a cost-optimized mix (Opus for classify/draft, Sonnet for fetch/trash, DeepSeek for plan/report) at ~$0.33/run (−38% vs. all-Opus).
version: 0.3.0
author: Eragon
license: MIT
metadata:
  eragon:
    tags: [gmail, triage, multimodel, routing, evaluation]
    related_skills: [gog]
---

# Gmail Triage — Per-Step Model Routing (Evaluation Harness)

## Overview

End-to-end Gmail triage workflow: fetch unread + actionable read mail, classify, draft replies (don't send), plan non-reply actions, report in 3 sections, auto-trash unimportant mail.

Each phase runs as **its own `sessions_spawn` subagent on a step-specific model with explicit context isolation**, so models can be swapped per row in the routing table without rewriting the skill. The current routing uses a cost-optimized mix: Opus 4.6 for high-judgment steps (classify, draft), Sonnet 4.6 for tool-call-heavy steps (fetch, trash), and DeepSeek V4 Pro for lightweight steps (plan, report) — cutting per-run cost by ~38%.

## When to Use

- Evaluating per-step model routing for inbox triage (the primary use case today).
- Any time you want each phase isolated in its own subagent with its own model (no shared context, no transcript bleed between phases).

Don't use for:
- Routine inbox triage where one model is fine — this multi-step routing harness is slower than running the same workflow in one session.
- Composing one large reply from scratch — this skill is a triage harness, not a writer.

## Model Routing Table

**Edit this table to change per-step models. Nothing else changes.** The orchestrator reads this table and passes `model=<model>` to each `sessions_spawn` call.

To list available model IDs, run `session_status` or check `/status` in chat.
Confirmed working downgrade candidates: `anthropic/claude-sonnet-4.6` (fetch, trash), `deepseek/deepseek-v4-pro` (plan, report)

| Step ID  | Phase             | Model                          | Provider    | Isolation   | Rationale                                                     |
|----------|-------------------|--------------------------------|-------------|-------------|---------------------------------------------------------------|
| fetch    | Phase 1: Fetch    | anthropic/claude-sonnet-4.6    | openrouter  | mode="run"  | Tool-call heavy but structured; Sonnet handles reliably.      |
| classify | Phase 2: Classify | anthropic/claude-opus-4.6      | openrouter  | mode="run"  | Nuanced judgment (important vs noise). Quality ceiling.       |
| draft    | Phase 3: Draft    | anthropic/claude-opus-4.6      | openrouter  | mode="run"  | Tone-matching + thread context. Quality ceiling.              |
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

3. **Verify model routing after every spawn.** After each `sessions_spawn` completes, check two things:

   **(a) Check `modelApplied` in the spawn result.**
   Eragon returns `modelApplied: true` when the model override was applied successfully. If `modelApplied` is `false` or missing when a model was requested, abort — the child ran on the default model, not the routing table's model.

   **(b) Check the `MODEL_USED:` line in the child's output.**
   Every step prompt begins with a `ROUTING_VERIFY` instruction that asks the child to echo its model ID as the first line. After capturing output, verify the first line matches `MODEL_USED:<expected_model>`. If it doesn't match or is missing, abort.

   **Both checks must pass.** `modelApplied` catches Eragon-level fallback; `MODEL_USED:` catches model self-reporting errors.

   If either check fails: **abort the entire run**, report which step failed, and do NOT retry on a different model — that poisons the routing evaluation.

4. If any step errors, times out (`runTimeoutSeconds=600`), or fails model verification, abort the whole run. Report which step + which model + the failure reason.

## MockMail MCP Server

For benchmarking, email access is provided by **MockMail** — a local MCP server backed by a SQLite snapshot of a real inbox. Tools are prefixed `MOCKMAIL_` (e.g. `MOCKMAIL_FETCH_EMAILS`, `MOCKMAIL_CREATE_EMAIL_DRAFT`) to avoid conflicts with Composio's built-in Gmail integration.

**Setup on each benchmark instance (one-time):**
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

## Prerequisites


- Google Workspace OAuth must be connected. Verify:
  ```bash
  curl -s "${ERAGON_GATEWAY_URL:-http://localhost:18789}/__eragon_claw__/oauth/google-workspace/token" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('access_token') else 'FAIL')"
  ```
  If FAIL, direct the user to connect at: `https://lance100.eragon.ai/__eragon_claw__/oauth/google-workspace/authorize`

## Gmail API Helper (used inside every step)

Every subagent task includes this token-fetch pattern so steps are self-contained:

```bash
GW="${ERAGON_GATEWAY_URL:-http://localhost:18789}"
TOKEN=$(curl -s "$GW/__eragon_claw__/oauth/google-workspace/token" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
GMAIL="https://www.googleapis.com/gmail/v1/users/me"
```

All Gmail REST calls then use `-H "Authorization: Bearer $TOKEN"`.

**Do NOT use `gog` CLI** — it cannot use gateway-managed tokens.
**Do NOT read auth-profiles.json directly** — use the gateway token endpoint only.

## Inputs

Single optional arg passed in the orchestrator's user message:
- `max_emails` (default 100): cap on emails pulled in Phase 1.

## Shared Preamble (prepend to every step prompt)

```
ROUTING_VERIFY: Echo the first line of your response as: MODEL_USED:<your model id>

You are running as one isolated step of a Gmail triage workflow.

Gmail access — token fetch (run this before any Gmail API call):
  GW="${ERAGON_GATEWAY_URL:-http://localhost:18789}"
  TOKEN=$(curl -s "$GW/__eragon_claw__/oauth/google-workspace/token" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
  GMAIL="https://www.googleapis.com/gmail/v1/users/me"

Rules:
- Never auto-send email. Drafts only. Trashing is allowed (recoverable 30d).
- When in doubt about classification, prefer "important_fyi" over "unimportant".
- Return your output as plain text or JSON only — no preamble after MODEL_USED, no sign-off, no markdown fences unless explicitly asked.
- Use exec() / shell commands for all Gmail API calls.
```

---

## Steps

### Step `fetch` — Phase 1: Fetch candidate emails

**Upstream input:** none.

Full prompt to subagent (after shared preamble):

```
Task: fetch candidate inbox emails for triage.

1. Fetch unread inbox messages (paginate if nextPageToken present):
   curl -s "$GMAIL/messages?q=is:unread+in:inbox&maxResults=50" -H "Authorization: Bearer $TOKEN"

2. Fetch recent read actionable messages:
   curl -s "$GMAIL/messages?q=is:read+in:inbox+-category:promotions+-category:social+newer_than:14d&maxResults=50" -H "Authorization: Bearer $TOKEN"

3. For each message ID from both lists, fetch metadata:
   curl -s "$GMAIL/messages/<ID>?format=metadata&metadataHeaders=From,Subject,Date" \
     -H "Authorization: Bearer $TOKEN"

4. Dedupe by threadId. Cap total at {{max_emails}}.

5. For each surviving message extract: id, threadId, from, subject, snippet, internalDate, labelIds.

Note: If the response has a nextPageToken, fetch the next page using &pageToken=<token>
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

2. Create the draft via Gmail API:
   curl -s -X POST "$GMAIL/drafts" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "message": {
         "threadId": "<threadId>",
         "raw": "<base64url-encoded RFC 2822 message with To/Subject/body>"
       }
     }'

   To base64url-encode the raw message in shell:
   printf '%s' "To: <to>\r\nSubject: Re: <subject>\r\nContent-Type: text/plain\r\n\r\n<body>" \
     | python3 -c "import sys,base64; print(base64.urlsafe_b64encode(sys.stdin.buffer.read()).decode())"

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
  curl -s -X POST "$GMAIL/messages/<id>/trash" \
    -H "Authorization: Bearer $TOKEN"

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
| classify | anthropic/claude-opus-4.6    | ✅           | ✅             | completed   | 18.1        |
| draft    | anthropic/claude-opus-4.6    | ✅           | ✅             | completed   | 34.7        |
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

This is what the LLM judge ingests to decide which rows can be downgraded.

---

## How the LLM Judge Refines Routing Later

1. Run this skill end-to-end with **all-Opus** on, say, 5 different inbox snapshots → collect (output, latency) per step per run.
2. Re-run each individual step with a candidate cheaper model using the **same `{{prior_step.output}}`** from the Opus run as input. Holding upstream constant isolates the swap.
3. Judge model scores each candidate output against the Opus baseline on a 1–5 rubric (correctness, completeness, format adherence). Anything ≥ 4 on a cheaper model wins that step.
4. Update the routing table in this file. No code changes — just edit the table.

**Why all-Opus first:** gives the judge a quality ceiling to grade against. If we started on a mix, a low score could be the model *or* the step being hard.

---

## Common Pitfalls

1. **Silent model fallback.** Eragon's `sessions_spawn` returns `modelApplied: true/false` to indicate whether the model override took effect. If the requested model ID is invalid or unavailable, `modelApplied` will be `false` and the child runs on the default model — silently. **Always check `modelApplied` after every spawn.** Additionally, verify the `MODEL_USED:` line in the child's output as a second layer of defense. Abort on any mismatch.

2. **`mode="run"` is already context-isolated.** In Eragon, `mode="run"` subagents do NOT inherit the parent transcript — they start fresh with only the `task` string. This is the correct behavior for this skill. Always use `mode="run"`, never `mode="session"` (which would make the child persistent and potentially inherit context if thread-bound). Each child only needs the structured upstream JSON passed via the `task` parameter.

3. **Don't retry a failed step on a different model.** Defeats the routing-evaluation purpose. Fail loudly, don't fall back.

4. **Pin upstream inputs for candidate runs.** When the judge swaps a cheaper model into step N, the inputs to step N must be the *Opus baseline* outputs from steps 1..N-1 — not the candidate's own upstream. Save baseline outputs to files before running candidate comparisons.

5. **`AGENTS.md` is auto-inherited; persona/identity/memory files are not.** Stable triage rules should go in `AGENTS.md` or in the task brief. Don't rely on parent session context to ship rules to children — `mode="run"` children don't get it.

6. **Gmail API pagination.** `messages.list` returns at most 500 IDs per page and defaults to 100. Use `nextPageToken` to paginate. Note "TRUNCATED:Y" if you hit the cap so downstream steps know the sample is partial.

7. **Gateway token expiry.** The gateway endpoint refreshes tokens automatically, but if it returns an error, the user needs to re-authorize at the OAuth link. Don't cache the token across step calls — re-fetch at the top of each subagent.

8. **Subagent timeout too low.** Phase 3 (draft) can run 60–120 s on a busy inbox. Keep `runTimeoutSeconds=600` on every step.

9. **base64url encoding for Gmail draft raw field.** The raw message must be RFC 2822 format, base64url-encoded (not standard base64). Use `base64.urlsafe_b64encode` in Python; strip `=` padding if needed by the API.

10. **Draft vs Send.** The Gmail API `/drafts` endpoint creates a draft. `/messages/send` sends immediately. This skill NEVER calls `/messages/send`.

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
- [ ] No email was sent (only drafts created via `/drafts` endpoint).
- [ ] No permanent deletes — `/trash` only, never `/delete`.
- [ ] Google Workspace OAuth token was valid for the entire run (no 401 errors in step outputs).
