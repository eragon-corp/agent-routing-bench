---
name: soc2-auditor-comparison
description: Compare two SOC 2 auditor quotes by searching Gmail and Slack for all relevant conversations, extracting key terms from each proposal, and producing a decision (Advantage Partners vs Prescient Security, or neither) based on timeline, reputation, and price — in that order.
version: 1.0.0
author: Eragon
license: MIT
metadata:
  eragon:
    tags: [soc2, vendor-comparison, procurement, multimodel, routing]
    related_skills: [email-triage-multimodel]
---

# SOC 2 Auditor Comparison — Per-Step Model Routing

## Model Routing Table

**Edit this table to change per-step models. Nothing else changes.**

| Step ID    | Phase                        | Model                          | Provider   | Isolation  | Rationale                                                        |
|------------|------------------------------|--------------------------------|------------|------------|------------------------------------------------------------------|
| fetch      | Phase 1: Fetch emails        | anthropic/claude-opus-4.8      | openrouter | mode="run" | Tool-call + judgment; needs to find all relevant threads.        |
| slack      | Phase 2: Fetch Slack context | anthropic/claude-sonnet-4.6    | openrouter | mode="run" | Tool-call heavy, structured extraction.                          |
| extract    | Phase 3: Extract terms       | anthropic/claude-opus-4.8      | openrouter | mode="run" | Nuanced extraction from messy email threads.                     |
| assess     | Phase 4: Assess & flag       | anthropic/claude-opus-4.8      | openrouter | mode="run" | Judgment-heavy: compare factors and flag issues.                 |
| decide     | Phase 5: Decision            | anthropic/claude-opus-4.8      | openrouter | mode="run" | Final synthesis and recommendation.                              |

## Routing Protocol (orchestrator must follow exactly)

1. Treat the routing table as the **single source of truth** for `model` per `step_id`.
2. For each step in order (fetch → slack → extract → assess → decide):
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
   - Save the captured output to a per-step file before continuing, so intermediate work is available for inspection and reruns.

3. **Verify model routing after every spawn.**
   - **(a)** Check `modelApplied: true` in spawn result. If false/missing, abort.
   - **(b)** Verify the first line of child output matches `MODEL_USED:<expected_model>`. If mismatch or missing, abort.
   - If either check fails: abort the entire run. Do NOT retry on a different model.

4. If any step errors, times out, or fails model verification, abort and report which step + model + failure reason.

**Context isolation per step:**
- `fetch` — no upstream input
- `slack` — no upstream input (runs independently of fetch, Slack is a separate source)
- `extract` — needs `fetch.output` + `slack.output`
- `assess` — needs `extract.output`
- `decide` — needs `extract.output` + `assess.output`

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
Task: fetch all Gmail conversations related to the SOC 2 auditor comparison.

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

### Step `assess` — Phase 4: Assess & Flag Issues

**Upstream input:** `extract.output`

```
Task: assess both firms on the three decision factors.

## Extracted data:
{{extract.output}}

---

Return JSON:
{
  "advantage_partners": {
    "timeline_assessment": "...",
    "reputation_assessment": "...",
    "price_assessment": "...",
    "overall_assessment": "...",
    "issues_to_discuss": ["..."]
  },
  "prescient_security": { <same shape> }
}
```

### Step `decide` — Phase 5: Final Decision

**Upstream input:** `extract.output` + `assess.output`

```
Task: produce the final comparison report and decision.

## Extracted data:
{{extract.output}}

## Assessment:
{{assess.output}}

---

Produce this report in plain markdown:

## SOC 2 Auditor Comparison Report

### Firm Summaries
For each firm: 3–5 bullets covering price, timeline, inclusions, responsiveness, reputation. Quote actual numbers and dates.

### Factor Comparison
| Factor      | Advantage Partners    | Prescient Security    |
|-------------|-----------------------|-----------------------|
| Timeline    | rationale             | rationale             |
| Reputation  | rationale             | rationale             |
| Price       | rationale             | rationale             |

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
  assess:  <Xs> | model: <model>
  decide:  <Xs> | model: <model>

--- REPORT ---
{{decide.output}}

--- ROUTING AUDIT ---
| Step    | Model                       | modelApplied | MODEL_USED verified | wallclock_s |
|---------|-----------------------------|--------------|---------------------|-------------|
| fetch   | anthropic/claude-opus-4.8   | -            | -                   | Xs          |
| slack   | anthropic/claude-sonnet-4.6 | -            | -                   | Xs          |
| extract | anthropic/claude-opus-4.8   | -            | -                   | Xs          |
| assess  | anthropic/claude-opus-4.8   | -            | -                   | Xs          |
| decide  | anthropic/claude-opus-4.8   | -            | -                   | Xs          |
```

## Verification Checklist

- [ ] Routing table is single source of truth.
- [ ] All steps run via `sessions_spawn(mode="run")`.
- [ ] `modelApplied` and `MODEL_USED:` both verified after every spawn.
- [ ] Routing Audit table appended to final output.
- [ ] `slack` step handles connection failure gracefully.
- [ ] `extract` uses null for unknowns — no fabrication.
- [ ] Final verdict is one of three options: Advantage Partners / Prescient Security / Neither.
