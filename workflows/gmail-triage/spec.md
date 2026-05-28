# Benchmark Spec: gmail-triage

## Metadata

```yaml
workflow: gmail-triage
version: 0.3.0
requires_setup: true
parallelizable: false
parallel_reason: "Side-effectful Gmail writes (drafts, trash). Sequential runs required to avoid inbox state collisions."
steps_evaluated: [fetch, classify, draft, plan, report, trash]
runs_per_method: 5
```

## Methods Under Comparison

| Method ID          | Description                                                                                         | Model(s)                                                           | Routing Table Used? |
|--------------------|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------|---------------------|
| `cowork`           | Claude Cowork (no routing). Single model, no per-step routing.                                      | `openrouter/anthropic/claude-sonnet-4.6` via `openrouter` provider | NO                  |
| `eragon-norouting` | Eragon all-Opus baseline. Forces every step to Opus — no routing table.                             | `anthropic/claude-opus-4.6` via `anthropic` provider               | NO (all-Opus)       |
| `eragon-routing`   | Eragon with routing. Uses the per-step routing table from `skill.md` (cost-optimized mix).          | Per routing table in `skill.md`                                    | YES                 |

**Rationale for all-Opus baseline:** `eragon-norouting` establishes a quality ceiling. The judge grades all other methods against this ceiling to determine whether cheaper routing degrades output quality.

## Setup Requirements

`requires_setup: true` — This workflow requires a live Gmail inbox pre-loaded with a realistic mix of emails before each run. A suitable inbox snapshot should contain:

- At least 10 unread messages
- At least 5 emails requiring replies (important_action)
- At least 5 FYI emails (important_fyi)
- At least 10 unimportant emails (newsletters, promos, cold outreach)
- At least 2 emails with ambiguous classification (borderline cases)

**Pre-run checklist:**
1. Confirm Google Workspace OAuth is connected:
   ```bash
   curl -s "${ERAGON_GATEWAY_URL:-http://localhost:18789}/__eragon_claw__/oauth/google-workspace/token" \
     | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('access_token') else 'FAIL')"
   ```
2. Snapshot inbox state (email IDs, label states) before each run for teardown.
3. Ensure no pending drafts from prior runs pollute the inbox.

## Teardown

After each run, restore the inbox to its pre-run state:

1. **Delete drafts** created during the run: use draft IDs from `draft.output` to DELETE each via `DELETE /gmail/v1/users/me/drafts/<draft_id>`.
2. **Restore trashed emails**: for each ID in `trash.output.trashed`, call `POST /gmail/v1/users/me/messages/<id>/untrash`.
3. Verify inbox state matches the pre-run snapshot before starting the next run.

**Teardown must complete successfully before the next run begins.** If teardown fails, stop the run sequence and alert the operator.

## Parallelism

`parallelizable: false`

Runs MUST be sequential. Gmail writes (drafts, trash) are side-effectful and mutate shared inbox state. Running two methods concurrently against the same inbox would produce different inputs for each step (e.g., method A's trash affects method B's fetch), invalidating the comparison. Each method must be run to completion and the inbox restored before the next method begins.

## Rubric: D1–D4 (1–5 per dimension, /20 per step)

| Dimension | Code | Description                                                                                                  | Score 1 (Fail)                                   | Score 3 (Adequate)                                        | Score 5 (Excellent)                                                |
|-----------|------|--------------------------------------------------------------------------------------------------------------|--------------------------------------------------|-----------------------------------------------------------|--------------------------------------------------------------------|
| Correctness       | D1 | Output is factually accurate and contains no hallucinated IDs, addresses, subjects, or actions.              | Multiple fabricated IDs or facts                 | Mostly accurate with minor factual slippage               | Fully grounded in provided email data; zero hallucinations         |
| Completeness      | D2 | All required output fields and emails are processed; no silent drops.                                        | Missing >20% of required emails or fields        | Most required content present; minor omissions            | All emails and fields processed; explicitly notes truncations      |
| Format Adherence  | D3 | Output matches the exact JSON schema or markdown structure specified in the step prompt.                     | Output is wrong format or unparseable            | Parseable but schema deviations (missing/extra keys)      | Exact schema, all required keys, types correct                     |
| Faithfulness      | D4 | Downstream steps use only the data passed in `task`; no hallucinated upstream context; no silent upgrades.  | Fabricates upstream data or invents email facts  | Mostly faithful; minor unsupported inferences             | Strictly grounded in upstream JSON; `[CONFIRM]` tags on gaps       |

**Per-step score:** D1 + D2 + D3 + D4 = /20
**Run total:** sum across all evaluated steps = /120

## Steps Evaluated

### Step `fetch` (Phase 1)
- **D1 Correctness:** Do fetched email IDs, threadIDs, from addresses, subjects, and snippets match actual Gmail API responses? No fabricated fields.
- **D2 Completeness:** Were both unread and recent read actionable emails fetched? Was pagination used if needed? Was `truncated` field set correctly?
- **D3 Format Adherence:** Does output match the exact JSON schema: `{emails: [...], truncated: bool, total_fetched: N}`? Are all required per-email fields present?
- **D4 Faithfulness:** No upstream context assumed; only Gmail API responses used.

### Step `classify` (Phase 2)
- **D1 Correctness:** Are important_action/important_fyi/unimportant assignments defensible given the email content? Were borderline cases conservatively assigned to `important_fyi` per the rule?
- **D2 Completeness:** Was every email from `fetch.output` classified? Were any silently dropped?
- **D3 Format Adherence:** Output matches `{important_action: [...], important_fyi: [...], unimportant: [...], rationale_by_id: {...}}`?
- **D4 Faithfulness:** Classifications based only on the email content in `fetch.output`; no invented prior knowledge.

### Step `draft` (Phase 3)
- **D1 Correctness:** Drafts are factually grounded in the email thread. `[CONFIRM:<fact>]` tags used wherever a fact isn't in the thread. No invented addressee names.
- **D2 Completeness:** Were all `important_action` emails that need replies drafted? Were skipped emails documented with reasons?
- **D3 Format Adherence:** Output matches `{drafts: [...], skipped: [...]}`; each draft entry has all required fields including `draft_id` from the API response.
- **D4 Faithfulness:** Draft bodies grounded only in `fetch.output` + `classify.output`; no fabricated thread history.

### Step `plan` (Phase 4)
- **D1 Correctness:** Action plans are actionable and correctly reference deadlines/links present in the email. No invented links or dates.
- **D2 Completeness:** Were all important_action emails NOT in `drafts.drafts[].email_id` covered? None silently skipped?
- **D3 Format Adherence:** Output matches `{actions: [{email_id, what, when, where}, ...]}`?
- **D4 Faithfulness:** Plans based only on `fetch.output` + `classify.output` + `draft.output`; no invented facts.

### Step `report` (Phase 5)
- **D1 Correctness:** Draft IDs, action items, and FYI counts match the actual upstream outputs. Unimportant count matches `classify.unimportant` length.
- **D2 Completeness:** Are all 3 required sections present? Does the report cover all drafts, actions, and FYI items without omissions?
- **D3 Format Adherence:** Exact section headers (`## 1. Required Responses`, `## 2. Actions Required`, `## 3. FYI / Pending Review`) and footer line present?
- **D4 Faithfulness:** Report content derived only from the four upstream outputs; no invented email summaries.

### Step `trash` (Phase 6)
- **D1 Correctness:** Were only `unimportant` IDs trashed? No important_action or important_fyi IDs in the trashed list?
- **D2 Completeness:** Was every ID in `classify.unimportant` processed? Were failures recorded in `failed[]`?
- **D3 Format Adherence:** Output matches `{trashed: [...], failed: [...], top_senders: [...]}`?
- **D4 Faithfulness:** Only `classify.output.unimportant` IDs used as input; no IDs from other buckets.

## Judge Instructions

You are an LLM judge evaluating the output of a Gmail triage benchmark. You will receive:
1. This spec (rubric, step definitions, method descriptions)
2. The full `output.txt` from a single run
3. The `run.json` metadata (method, run_id, timestamp)

**Scoring procedure:**

For each of the 6 steps (`fetch`, `classify`, `draft`, `plan`, `report`, `trash`):

1. Locate the step's output in `output.txt` (look for `MODEL_USED:` lines as step boundaries, or step headers in the output).
2. Score D1, D2, D3, D4 each on a 1–5 integer scale using the rubric above.
3. For each dimension score, provide 1–2 sentences of **evidence** quoting specific output fragments that justify the score.
4. Compute the step total: D1 + D2 + D3 + D4 (max 20).

**Comparison guidance:**
- When scoring all 3 methods, evaluate each independently first, then note relative differences in the evidence.
- Do NOT artificially inflate the `eragon-routing` score because it uses cheaper models — grade only on output quality.
- Do NOT penalize `cowork` for lacking routing infrastructure — only score the output quality.
- The `eragon-norouting` all-Opus run is the quality ceiling; scores for other methods should be interpreted relative to it.

**Output format (strict JSON, no fences):**
```json
{
  "run_id": "...",
  "method": "...",
  "step_scores": {
    "fetch":    {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "classify": {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "draft":    {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "plan":     {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "report":   {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "trash":    {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}}
  },
  "run_total": N,
  "judge_notes": "..."
}
```
