---
name: soc2-auditor-comparison
description: Compare two SOC 2 auditor quotes by searching Gmail and Slack for all relevant conversations, extracting key terms from each proposal, and producing a ranked decision (Advantage Partners vs Prescient Security, or neither) based on timeline, reputation, and price — in that order.
version: 1.0.0
author: Eragon
license: MIT
metadata:
  eragon:
    tags: [soc2, vendor-comparison, procurement, multimodel, routing, evaluation]
    related_skills: [gmail-triage-multimodel]
---

# SOC 2 Auditor Comparison — Per-Step Model Routing

## Overview

End-to-end vendor comparison workflow for a SOC 2 Type 2 audit decision. Searches Gmail and Slack for all conversations involving both auditor candidates, extracts key proposal terms, scores each firm on the three decision factors (timeline, reputation, price), flags any issues requiring discussion, and delivers a clear decision with reasoning.

The two firms under evaluation:
- **Advantage Partners** — contact: Andrew Topanian (atopanian@advantage-partners.com)
- **Prescient Security / Prescient Assurance** — contact: Griffin Mello (griffin.mello@prescientsecurity.com)

Each phase runs as **its own `sessions_spawn` subagent on a step-specific model with explicit context isolation**.

## Model Routing Table

**Edit this table to change per-step models. Nothing else changes.**

| Step ID    | Phase                        | Model                          | Provider   | Isolation  | Rationale                                                        |
|------------|------------------------------|--------------------------------|------------|------------|------------------------------------------------------------------|
| fetch      | Phase 1: Fetch emails        | anthropic/claude-opus-4.6      | openrouter | mode="run" | Tool-call + judgment; needs to find all relevant threads.        |
| slack      | Phase 2: Fetch Slack context | anthropic/claude-sonnet-4.6    | openrouter | mode="run" | Tool-call heavy, structured extraction.                          |
| extract    | Phase 3: Extract terms       | anthropic/claude-opus-4.6      | openrouter | mode="run" | Nuanced extraction from messy email threads. Quality ceiling.    |
| score      | Phase 4: Score & flag        | anthropic/claude-opus-4.6      | openrouter | mode="run" | Judgment-heavy: weight three factors, flag issues. Quality ceiling. |
| decide     | Phase 5: Decision            | anthropic/claude-opus-4.6      | openrouter | mode="run" | Final synthesis and recommendation. Quality ceiling.             |

## Routing Protocol (orchestrator must follow exactly)

1. Treat the routing table as the **single source of truth** for `model` per `step_id`.
2. For each step in order (fetch → slack → extract → score → decide):
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
         label     = "soc2-<step_id>",
     )
     ```
   - Record wall-clock elapsed time after completion.
   - Capture the subagent's reply as `{{<step_id>.output}}`.

3. **Verify model routing after every spawn.**
   - **(a)** Check `modelApplied: true` in spawn result. If false/missing, abort.
   - **(b)** Verify the first line of child output matches `MODEL_USED:<expected_model>`. If mismatch or missing, abort.
   - If either check fails: abort the entire run. Do NOT retry on a different model.

4. If any step errors, times out, or fails model verification, abort and report which step + model + failure reason.

**Context isolation per step:**
- `fetch` — no upstream input
- `slack` — no upstream input (runs independently of fetch, Slack is a separate source)
- `extract` — needs `fetch.output` + `slack.output`
- `score` — needs `extract.output`
- `decide` — needs `extract.output` + `score.output`

---

## Inputs

No required inputs — the workflow is self-contained. It knows the two firms and searches for all relevant communications automatically.

---

## Shared Preamble (prepend to every step prompt)

```
ROUTING_VERIFY: Echo the first line of your response as: MODEL_USED:<your model id>

You are running as one isolated step of a SOC 2 auditor comparison workflow. The two firms being compared are:
- Advantage Partners (contact: Andrew Topanian, atopanian@advantage-partners.com)
- Prescient Security / Prescient Assurance (contact: Griffin Mello, griffin.mello@prescientsecurity.com)

Decision factors in priority order: (1) timeline, (2) reputation, (3) price.
There is no Legal team — flag issues for internal discussion instead of legal review.

Return your output as plain JSON or structured text only. No preamble after MODEL_USED, no sign-off, no markdown fences unless explicitly asked.
```

---

## Steps

### Step `fetch` — Phase 1: Fetch Gmail Context

**Upstream input:** none.

```
Task: fetch all Gmail conversations related to the SOC 2 auditor evaluation.

Search the following queries and return ALL matching emails with full body text:

1. query: "Advantage Partners SOC 2" — up to 30 results
2. query: "Prescient Security SOC 2" — up to 30 results
3. query: "SOC 2 auditor" — up to 20 results
4. query: "Griffin Mello" — up to 10 results
5. query: "Andrew Topanian" — up to 10 results

Use MOCKMAIL_FETCH_EMAILS for each query with fetch_full_message: true.
Deduplicate by messageId.

For each unique email return:
{
  "messageId": "...", "threadId": "...", "sender": "...",
  "subject": "...", "date": "...", "labelIds": [...], "body": "<full body>"
}

Return JSON array. If a query returns 0 results, note it and continue.
```

### Step `slack` — Phase 2: Fetch Slack Context

**Upstream input:** none (independent of fetch).

```
Task: search Slack for any conversations mentioning either SOC 2 auditor.

Search using SLACK_SEARCH_MESSAGES for:
1. "SOC 2" OR "SOC2"
2. "Prescient"
3. "Advantage Partners"
4. "Griffin Mello"
5. "Andrew Topanian"
6. "auditor"

Return up to 10 results per search. Deduplicate by ts.

For each message: { "ts": "...", "channel": "...", "sender": "...", "text": "..." }

If Slack is unavailable, return: {"slack_available": false, "messages": []}
```

### Step `extract` — Phase 3: Extract Proposal Terms

**Upstream input:** `fetch.output` + `slack.output`

```
Task: extract all structured proposal information for both firms.

## Gmail emails:
{{fetch.output}}

## Slack messages:
{{slack.output}}

---

For each firm extract (use null for anything not found — do not fabricate):

{
  "firm": "...",
  "contact": "...",
  "price": "<$ amount or null>",
  "timeline_total": "<duration or null>",
  "timeline_observation_period": "<duration or null>",
  "timeline_reporting": "<post-observation duration or null>",
  "vanta_integration": "yes/no/unknown",
  "engagement_letter_sent": "yes/no/unknown",
  "engagement_letter_signed": "yes/no/unknown",
  "responsiveness_signals": ["<evidence of fast or slow response>"],
  "reputation_signals": ["<evidence of quality, references, Vanta partnership>"],
  "scope_inclusions": ["<readiness review, pen testing, etc.>"],
  "issues_to_discuss": ["<missing info, contractual concerns, process gaps>"],
  "internal_sentiment": "<what internal team said>",
  "raw_quote_link": "<proposal URL if found>"
}

Return JSON: { "advantage_partners": {...}, "prescient_security": {...} }
```

### Step `score` — Phase 4: Score & Flag Issues

**Upstream input:** `extract.output`

```
Task: score both firms on the three decision factors.

## Extracted data:
{{extract.output}}

---

Score each firm 1–5 per factor. Priority order: timeline (×3), reputation (×2), price (×1).

TIMELINE scoring:
5 = Fastest + proactive, no delays
4 = Competitive timeline, minor unknowns
3 = Average, some responsiveness concerns
2 = Slower OR significant responsiveness issues already observed
1 = Timeline unknown AND major red flags

REPUTATION scoring:
5 = Strong: known Vanta partner, references, professional process
4 = Good signals, minor gaps
3 = Neutral — limited signal
2 = Some concerns
1 = Red flags in behavior or communications

PRICE scoring:
5 = Clearly cheaper
4 = Slightly cheaper or equivalent with more inclusions
3 = Equivalent or one price unknown
2 = Slightly more expensive
1 = Clearly more expensive

Weighted score = (timeline × 3) + (reputation × 2) + (price × 1) — max 30.

Return JSON:
{
  "advantage_partners": {
    "timeline_score": N, "timeline_rationale": "...",
    "reputation_score": N, "reputation_rationale": "...",
    "price_score": N, "price_rationale": "...",
    "weighted_score": N,
    "issues_to_discuss": ["..."]
  },
  "prescient_security": { <same shape> }
}
```

### Step `decide` — Phase 5: Final Decision

**Upstream input:** `extract.output` + `score.output`

```
Task: produce the final comparison report and decision.

## Extracted data:
{{extract.output}}

## Scores:
{{score.output}}

---

Produce this report in plain markdown:

## SOC 2 Auditor Comparison Report

### Firm Summaries
For each firm: 3–5 bullets covering price, timeline, inclusions, responsiveness, reputation. Quote actual numbers and dates.

### Score Summary
| Factor (weight)     | Advantage Partners    | Prescient Security    |
|---------------------|-----------------------|-----------------------|
| Timeline (×3)       | N/5 — rationale       | N/5 — rationale       |
| Reputation (×2)     | N/5 — rationale       | N/5 — rationale       |
| Price (×1)          | N/5 — rationale       | N/5 — rationale       |
| **Weighted Total**  | **/30**               | **/30**               |

### Issues to Discuss
Numbered list of flagged items. For each: which firm, what the issue is, what action is needed.

### Final Verdict
**[Advantage Partners | Prescient Security | Neither — gather more information]**

2–3 sentences grounded in the three decision factors in priority order.
If "Neither": specify exactly what information is needed before proceeding.
```

---

## Final Orchestrator Output

```
SOC 2 AUDITOR COMPARISON — RUN COMPLETE

Step timings:
  fetch:   <Xs> | model: <model>
  slack:   <Xs> | model: <model>
  extract: <Xs> | model: <model>
  score:   <Xs> | model: <model>
  decide:  <Xs> | model: <model>

--- REPORT ---
{{decide.output}}

--- ROUTING AUDIT ---
| Step    | Model                       | modelApplied | MODEL_USED verified | wallclock_s |
|---------|-----------------------------|--------------|---------------------|-------------|
| fetch   | anthropic/claude-opus-4.6   | -            | -                   | Xs          |
| slack   | anthropic/claude-sonnet-4.6 | -            | -                   | Xs          |
| extract | anthropic/claude-opus-4.6   | -            | -                   | Xs          |
| score   | anthropic/claude-opus-4.6   | -            | -                   | Xs          |
| decide  | anthropic/claude-opus-4.6   | -            | -                   | Xs          |
```

---

## Common Pitfalls

1. **Slack not connected.** Handle gracefully — `slack` step returns `{"slack_available": false}` and extract notes this.
2. **Prescient price not in emails.** Proposal is behind a link. Return `price: null`, score neutral (3), flag it.
3. **Thread deduplication.** Same body appears in forwarded chains. Deduplicate by messageId.
4. **Internal sentiment is thin.** Only two people commented. Quote directly, don't over-weight.
5. **Model verification abort.** If `modelApplied` false on any step, abort immediately.

---

## Verification Checklist

- [ ] Routing table is single source of truth.
- [ ] All steps run via `sessions_spawn(mode="run")`.
- [ ] `modelApplied` and `MODEL_USED:` both verified after every spawn.
- [ ] Routing Audit table appended to final output.
- [ ] `slack` step handles connection failure gracefully.
- [ ] `extract` uses null for unknowns — no fabrication.
- [ ] `score` weights: timeline ×3, reputation ×2, price ×1.
- [ ] Final verdict is one of three options: Advantage Partners / Prescient Security / Neither.
