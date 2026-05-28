---
name: deep-research
description: Deep research on any well-defined topic using a multi-model subagent pipeline with Eragon canvas dashboard. Use when asked to research a topic in depth, investigate a subject, create a research brief, do a literature/market/technology survey, or produce a research dashboard. Seven isolated phases (scope, search, extract, analyze, synthesize-report, synthesize-data, dashboard) each run as their own sessions_spawn subagent with per-step model routing controlled by a single routing table. NOT for quick factual lookups (just use web_search directly) or opinion questions.
---

# Deep Research — Per-Step Model Routing with Canvas Dashboard

## Overview

End-to-end research workflow: refine a topic into searchable queries, search the web in parallel, extract and read sources, analyze findings for themes and contradictions, synthesize a structured report, and render an interactive HTML dashboard on Eragon's canvas.

Each phase runs as **its own `sessions_spawn` subagent on a step-specific model with explicit context isolation**, so an LLM judge can later swap the model per row in the routing table without rewriting the skill.

## When to Use

- Deep-diving into a topic: technology surveys, market analysis, policy research, competitive intelligence, literature reviews.
- When the user wants a visual dashboard summarizing findings (not just a text wall).
- Evaluating per-step model routing for research pipelines.

Don't use for:
- Quick factual questions — just use `web_search` directly.
- Opinions or creative writing — this is a research harness.
- Tasks requiring real-time data feeds or API integrations beyond web search.

## Model Routing Table

**Edit this table to change per-step models. Nothing else changes.**

| Step ID    | Phase                  | Model                       | Isolation   | Rationale                                                      |
|------------|------------------------|-----------------------------|-------------|----------------------------------------------------------------|
| scope      | Phase 1: Scope         | openrouter/anthropic/claude-sonnet-4.5 | mode="run"  | Nuanced query decomposition. Needs strong reasoning.           |
| search     | Phase 2: Search        | openrouter/anthropic/claude-haiku-4.5  | mode="run"  | Tool-call heavy (web_search). Quality ceiling baseline.        |
| extract    | Phase 3: Extract       | openrouter/anthropic/claude-sonnet-4.5 | mode="run"  | Tool-call heavy (web_fetch). Quality ceiling baseline.         |
| analyze    | Phase 4: Analyze       | openrouter/anthropic/claude-opus-4.6   | mode="run"  | Deep reasoning: themes, contradictions, evidence quality.      |
| synthesize-report | Phase 5a: Synthesize Report | openrouter/anthropic/claude-opus-4.6   | mode="run"  | Nuanced writing: executive summary, key findings, narrative.   |
| synthesize-data   | Phase 5b: Synthesize Data   | openrouter/anthropic/claude-sonnet-4.5 | mode="run"  | Structured JSON dashboard data from report + analysis.         |
| dashboard  | Phase 6: Dashboard     | openrouter/anthropic/claude-sonnet-4.5 | mode="run"  | HTML/CSS generation. Quality ceiling baseline.                 |

**Why all-Opus first:** Establishes a quality ceiling for every step before cheaper models are tried. The judge can later downgrade search/extract/dashboard to Sonnet or Haiku based on quality evaluation against this baseline.

**Context isolation per step:**
- `scope` — receives only the user's research topic
- `search` — receives `scope.output` (queries + focus areas)
- `extract` — receives `scope.output` + `search.output` (URLs + snippets)
- `analyze` — receives `scope.output` + `extract.output` (source summaries)
- `synthesize-report` — receives `scope.output` + `analyze.output` (themes + evidence)
- `synthesize-data` — receives `scope.output` + `analyze.output` + `synthesize-report.output` (report text + analysis for JSON extraction)
- `dashboard` — receives `scope.output` + `synthesize-data.output` (DASHBOARD_DATA JSON only)

## Routing Protocol (orchestrator must follow exactly)

1. Treat the routing table as the **single source of truth** for `model` per `step_id`.
2. For each step in order (scope → search → extract → analyze → synthesize-report → synthesize-data → dashboard):
   - Build the per-step prompt from the "Steps" section below, substituting `{{prior_step.output}}` placeholders with the captured output of earlier steps.
   - **Strict input scoping:** Each step's `task` string must contain ONLY the upstream outputs explicitly declared in that step's "Upstream input" line. Never include the full transcript, other steps' outputs, or orchestrator commentary. If you find yourself passing data not listed in the upstream spec, stop — you are violating isolation.
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
         label     = "research-<step_id>",
     )
     ```
   - Record wall-clock elapsed time after completion.
   - Capture the subagent's reply as `{{<step_id>.output}}`.

3. **Verify model routing after every spawn.** After each `sessions_spawn` completes:

   **(a) Check `modelApplied` in the spawn result.** If `false` or missing, abort.

   **(b) Check the `MODEL_USED:` line in the child's output.** Every step prompt begins with a `ROUTING_VERIFY` instruction. Verify the first line matches `MODEL_USED:<expected_model>`. If mismatch, abort.

   **Both checks must pass.** If either fails: abort the entire run, report which step failed.

4. **Schema validation between steps (mandatory).** After capturing each step's output, the orchestrator must validate it before proceeding to the next step:

   - **scope:** JSON-parse the output (after stripping the `MODEL_USED:` line). Required top-level keys: `core_question`, `sub_questions`, `bias_watchlist`, `total_queries`. Each entry in `sub_questions` must have: `id`, `question`, `queries`, `desired_source_types`. If any required key is missing, abort with: `"ABORT: scope output missing required key: <key>"`.
   - **search:** Required top-level keys: `results`, `total_unique`, `queries_executed`. Each entry in `results` must have: `url`, `title`, `snippet`, `related_sub_questions`. Abort on missing keys.
   - **extract:** Required top-level keys: `sources`, `failed_urls`, `total_extracted`. Each entry in `sources` must have: `url`, `title`, `summary`, `credibility`, `related_sub_questions`. Abort on missing keys.
   - **analyze:** Required top-level keys: `answers`, `themes`, `contradictions`, `evidence_quality`, `key_statistics`. Each entry in `answers` must have: `sub_question_id`, `question`, `consensus`, `supporting_sources`, `confidence`. Abort on missing keys.
   - **synthesize-report:** Output is markdown text (not JSON). Validate that it contains at least the headings: `## Executive Summary`, `## Key Findings`, `## Sources`. Abort if any heading is missing.
   - **synthesize-data:** JSON-parse the output (after stripping `MODEL_USED:`). Required top-level keys: `topic`, `executive_summary`, `finding_count`, `source_count`, `high_confidence_answers`, `medium_confidence_answers`, `low_confidence_answers`, `key_findings`, `key_stats`, `themes`, `contradictions`, `evidence_quality`, `sources`. Abort on missing keys or JSON parse failure.
   - **dashboard:** Output must start with `<!DOCTYPE html>` (after stripping `MODEL_USED:` line). Abort if not valid HTML opening.

   If JSON parsing fails for any JSON step, abort with: `"ABORT: <step_id> output is not valid JSON. Raw output (first 500 chars): <truncated>"`.

5. If any step errors, times out, fails model verification, or fails schema validation, abort the whole run. Report which step + which model + the failure reason. **Do NOT fall back to the orchestrator performing the failed step's work. Do NOT retry on a different model. Fail loudly.**

## Inputs

The orchestrator receives a single input from the user:
- `topic` (required): The research topic or question. Should be well-defined.
- `max_sources` (optional, default 20): Cap on total sources to extract.
- `depth` (optional, default "standard"): One of "quick" (5 queries), "standard" (10 queries), "deep" (20 queries).

## Shared Preamble (prepend to every step prompt)

ROUTING_VERIFY: Echo the first line of your response as: MODEL_USED:<your model id>
You are running as one isolated step of a deep research workflow.
Rules:

Return your output as plain text or JSON only — no preamble after MODEL_USED, no sign-off, no markdown fences unless explicitly asked.
Be thorough but concise. Prioritize accuracy over verbosity.
When uncertain about a claim, flag it with [UNCERTAIN] and note why.
Cite sources by URL wherever possible.


---

## Steps

### Step `scope` — Phase 1: Scope & Query Planning

**Upstream input:** User's research topic only.

Full prompt to subagent (after shared preamble):

Task: decompose a research topic into structured search queries and focus areas.
Research topic:{{topic}}
Depth: {{depth}}
Instructions:

Identify the core question and 3-5 sub-questions that together would comprehensively cover the topic.
For each sub-question, generate 2-4 specific web search queries optimized for finding authoritative sources.
Mix query types: definitional, comparative, recent news, academic/expert, data/statistics.
Include date-scoped queries where recency matters (e.g., "2024 2025" suffix).


Identify what types of sources would be most valuable (academic papers, industry reports, news, government data, expert blogs).
4. Populate `bias_watchlist` with topic-specific bias vectors to watch for during the research. This is REQUIRED and must not be empty. Include concrete bias categories such as: vendor-funded studies, industry lobbying, academic-only perspectives, geographic bias, recency bias, survivorship bias, conflicts of interest, ideological framing, etc. Tailor these to the specific topic — generic placeholders are not acceptable.
5. Total queries should match depth: quick=~5, standard=~10, deep=~20.

Return JSON only (no fences):
{
  "core_question": "...",
  "sub_questions": [
    {
      "id": "sq1",
      "question": "...",
      "queries": ["search query 1", "search query 2", ...],
      "desired_source_types": ["academic", "industry", ...]
    },
    ...
  ],
  "bias_watchlist": ["..."],
  "total_queries": <N>
}

Output capture: {{scope.output}}

Step search — Phase 2: Web Search
Upstream input: {{scope.output}}
Full prompt to subagent (after shared preamble):
Task: execute web searches for all planned queries and collect results.

Research plan:
{{scope.output}}

Instructions:
1. For each query in the research plan, call web_search with count=5.
2. Collect all results: title, URL, snippet.
3. Deduplicate by URL across all searches.
4. Rank results by relevance: prioritize authoritative domains (.gov, .edu, known publications, peer-reviewed), recency, and snippet relevance to the sub-question.
5. Cap total unique URLs at {{max_sources}} (default 20). Keep the best ones.
6. For each URL, note which sub-question(s) it relates to.

IMPORTANT: Execute searches sequentially (one web_search call at a time) to avoid rate limits.

Return JSON only (no f
...(truncated)...


    
  
        
    
      
        
    
      
      
    
  
        
    
  
      

      
        
    
      
      
    
  
      

      
        
    
      
      
    
  
      

      
        
    
      
      
      
    
  
        
    
  
      

      

      
        
          
    
      
      
      
    
  
        
        
    
      
        Copy as markdown
      
      
        Copy message ID
      
      
    
  
      
    
  
      

        
    
      
      
      Got chunks 1-4. Continue with chunks 5/9 through 9/9 — same format. Don't repeat 1-4. Just keep going from chunk 5/9 (chars 13000-16500) to the end. Send 5,6,7,8,9 in order.

    
  
        
      

        
    
      
      
      .

Return JSON only (no fences):
{
  "sources": [
    {
      "url": "...",
      "title": "...",
      "author": "...",
      "date": "...",
      "summary": "...",
      "key_facts": ["...", "..."],
      "key_quotes": ["...", "..."],
      "credibility": "high|medium|low",
      "related_sub_questions": ["sq1", "sq3"]
    },
    ...
  ],
  "failed_urls": [{"url": "...", "reason": "..."}],
  "total_extracted": <N>
}

Output capture: {{extract.output}}

Step analyze — Phase 4: Thematic Analysis
Upstream input: {{scope.output}} + {{extract.output}}
Full prompt to subagent (after shared preamble):
Task: perform deep thematic analysis across all extracted sources.

Research plan:
{{scope.output}}

Extracted sources:
{{extract.output}}

Instructions:
1. Answer each sub-question from the research plan using evidence from the sources. For each answer:
   - State the consensus view (if one exists) with supporting source URLs.
   - Note any dissenting views or contradictions with their source URLs.
   - Rate confidence: high (multiple high-credibility sources agree), medium (some agreement, some gaps), low (sparse or conflicting evidence).
   - CALIBRATION REQUIREMENT: Confidence ratings MUST be differentiated based on actual evidence quality per sub-question. If you find yourself rating all sub-questions the same confidence level, stop and re-evaluate — uniform confidence across all sub-questions is itself a strong signal of poor calibration. A sub-question supported by a single blog post CANNOT have the same confidence as one supported by multiple peer-reviewed sources. Deliberately interrogate each rating: "What would make me lower this?" If you can't articulate what would lower it, you haven't assessed it properly.

2. Identify cross-cutting themes that emerge across multiple sub-questions.

3. Identify key contradictions or debates where sources disagree.

4. Assess overall evidence quality:
   - How many sources are high-credibility vs low?
   - Are there important gaps (questions with no good sources)?
   - Are there potential biases in the source set?

5. Extract the top 5-10 most important statistics or data points with citations.

Return JSON only (no fences):
{
  "answers": [
    {
      "sub_question_id": "sq1",
      "question": "...",
      "consensus": "...",
      "supporting_sources": ["url1", "url2"],
      "dissenting_views": [{"view": "...", "sources": ["url3"]}],
      "confidence": "high|medium|low"
    },
    ...
  ],
  "themes": [
    {"theme": "...", "description": "...", "supporting_sources": ["url1", "url2"]},
    ...
  ],
  "contradictions": [
    {"topic": "...", "position_a": "...", "sources_a": ["..."], "position_b": "...", "sources_b": ["..."]},
    ...
  ],
  "evidence_quality": {
    "high_credibility_count": <N>,
    "medium_credibility_count": <N>,
    "low_credibility_count": <N>,
    "gaps": ["..."],
    "potential_biases": ["..."]
  },
  "key_statistics": [
    {"stat": "...", "source_url": "...", "context": "..."},
    ...
  ]
}

Output capture: {{analyze.output}}

Step synthesize-report — Phase 5a: Report Synthesis (Markdown Only)
Upstream input: {{scope.output}} + {{analyze.output}}
Full prompt to subagent (after shared preamble):

Task: synthesize the analysis into a structured research report. Output ONLY the markdown report — do NOT include any JSON or DASHBOARD_DATA block.
Research plan:{{scope.output}}
Analysis:{{analyze.output}}
Instructions:Produce a structured report with these exact sections. Write in clear, professional prose.Do NOT use markdown fences. Use markdown headings and formatting directly.
Research Report: {{topic}}
Executive Summary
3-5 sentences capturing the most important findings. Lead with the single most significant insight.
Key Findings
For each major finding (aim for 5-8):

Finding title — 2-3 sentence explanation with source citations as [Source: url].
Confidence level noted parenthetically.

Detailed Analysis
For each sub-question from the research plan:
[Sub-question text]

Answer the question in 1-2 paragraphs.
Cite sources as [Source: url].
Note confidence level and any caveats.

Key Statistics & Data
Bulleted list of the most impactful numbers, each with source citation.
Themes & Patterns
Describe 3-5 cross-cutting themes with evidence.
Contradictions & Open Questions
Where sources disagree or evidence is thin. What further research would help.
Source Quality Assessment
Brief summary of evidence strength, gaps, and potential biases.
Sources
Numbered list of all sources cited: [N] Title — URL (credibility: high/medium/low)
Return ONLY the full report as plain text (markdown formatted, no fences around the whole thing).Do NOT append any JSON, DASHBOARD_DATA, or structured data after the report. That will be handled by a separate step.

Output capture: `{{synthesize-report.output}}` — markdown report only, no JSON.

---

### Step `synthesize-data` — Phase 5b: Dashboard Data Extraction (JSON Only)

**Upstream input:** `{{scope.output}}` + `{{analyze.output}}` + `{{synthesize-report.output}}`

Full prompt to subagent (after shared preamble):

Task: produce a structured JSON summary of the research findings for dashboard rendering. Output ONLY valid JSON — no markdown, no prose, no fences.
Research plan:{{scope.output}}
Analysis (structured data):{{analyze.output}}
Research report (for reference — extract dashboard data from this + analysis):{{synthesize-report.output}}
Instructions:Using the analysis data and the research report above, produce a single JSON object with the following structure. Every field is REQUIRED. Output ONLY the JSON — no markdown, no commentary, no fences.
{  "topic": "...",  "executive_summary": "3-5 sentence summary from the report",  "finding_count": <N>,  "source_count": <N>,  "high_confidence_answers": <N>,  "medium_confidence_answers": <N>,  "low_confidence_answers": <N>,  "key_findings": [{"title": "...", "summary": "...", "confidence": "high|medium|low"}],  "key_stats": [{"stat": "...", "source": "url"}],  "themes": [{"theme": "...", "description": "..."}],  "contradictions": [{"topic": "...", "summary": "..."}],  "evidence_quality": {"high": <N>, "medium": <N>, "low": <N>, "gaps": <N>},  "sources": [{"title": "...", "url": "...", "credibility": "high|medium|low"}]}
Ensure:

finding_count matches the length of key_findings
source_count matches the length of sources
- Confidence counts match the actual distribution from analysis.answers
- All URLs are real URLs from the analysis, not fabricated

Output capture: {{synthesize-data.output}} — pure JSON, validated by orchestrator before passing to dashboard step.

Step dashboard — Phase 6: Canvas Dashboard Generation
Upstream input: {{scope.output}} + {{synthesize-data.output}} (validated DASHBOARD_DATA JSON).
Full prompt to subagent (after shared preamble):
Task: generate a self-contained HTML dashboard file for the research findings.

Research plan:
{{scope.output}}

Dashboard data (valid JSON):
{{synthesize-data.output}}

Instructions:
1. The dashboard data JSON is provided directly above. Use it as the data source for rendering.
2. Generate a single self-contained HTML file (inline CSS and JS, no external dependencies) that renders an interactive research dashboard.

Design requirements:
- Modern, clean design with a dark theme (dark gray background #1a1a2e, card backgrounds #16213e, accent color #0f3460, highlight #e94560).
- Responsive layout using CSS Grid.
- Dashboard sections:
  a. **Header**: Topic title, executive summary, date generated.
  b. **Stats Bar**: Cards showing: total sources, total findings, confidence breakdown (high/medium/low as colored badges).
  c. **Key Findings**: Expandable cards for each finding with confidence indicator (green/yellow/red dot).
  d. **Key Statistics**: Highlighted stat cards with source attribution.
  e. **Themes**: Visual theme cards with descriptions.
  f. **Contradictions & Open Questions**: Flagged items with warning styling.
  g. **Evidence Quality**: Visual bar showing high/medium/low source distribution.
  h. **Sources**: Collapsible table with title, URL (clickable), and credibility badge.

Interactive features:
- Click to expand/collapse findings and sources sections.
- Smooth CSS transitions.
- Confidence filter buttons (show all / high only / medium+ only).

3. The HTML file must be completely self-contained — all styles and scripts inline.
4. Total file should be under 50KB.

Return ONLY the complete HTML file content, starting with <!DOCTYPE html> and ending with </html>.
No other text before or after (except the MODEL_USED line which must be first).

Output capture: {{dashboard.output}} — raw HTML string.

Final Orchestrator Output
After all 7 steps succeed, the orchestrator must:

Use {{synthesize-report.output}} as the markdown report (it contains only the report, no JSON).
Write {{dashboard.output}} to a file in the workspace: research-dashboard-<timestamp>.html
Present the dashboard using Eragon's canvas tool:
Write the HTML to the workspace
Use canvas action:present with the file URL, OR if no nodes are connected, inform the user the HTML file is ready and display the markdown report directly.


Reply with:
The markdown report (from synthesize-report).
A line: **Dashboard saved:** research-dashboard-<timestamp>.html
If canvas was presented: **Dashboard is live on canvas.**


Append a Routing Audit footer:

**CRITICAL: The dashboard step (Phase 6) MUST always be spawned as its own subagent via `sessions_spawn(mode="run")`. The orchestrator must NEVER fall back to generating the HTML itself, even if upstream data is invalid or the dashboard subagent fails. If `synthesize-data` output is invalid JSON, abort the entire run with an error identifying the failure point. If the dashboard subagent fails, abort the entire run. No fallback to orchestrator-generated HTML is permitted — this violates context isolation and bypasses model verification gates.**


Routing Audit



step
model
modelApplied
model_verified
exit_status
wallclock_s



scope
openrouter/anthropic/claude-opus-4.6
✅
✅
completed
...


search
openrouter/anthropic/claude-opus-4.6
✅
✅
completed
...


extract
openrouter/anthropic/claude-opus-4.6
✅
✅
completed
...


analyze
openrouter/anthropic/claude-opus-4.6
✅
✅
completed
...


synthesize-report
openrouter/anthropic/claude-opus-4.6
✅
✅
completed
...


synthesize-data
openrouter/anthropic/claude-opus-4.6
✅
✅
completed
...


dashboard
openrouter/anthropic/claude-opus-4.6
✅
✅
completed
...



---

## How the LLM Judge Refines Routing Later

1. Run this skill end-to-end with the current routing on several diverse topics → collect (output quality, latency) per step per run.
2. Re-run each individual step with a candidate cheaper model using the **same upstream inputs** from the baseline run. Holding upstream constant isolates the swap.
3. Judge model scores each candidate output against the baseline on a 1–5 rubric (correctness, completeness, source quality, format adherence). Anything ≥ 4 on a cheaper model wins that step.
4. Update the routing table in this file. No code changes — just edit the table.

**Candidate downgrades to evaluate:**
- `search` → `openrouter/anthropic/claude-sonnet-4-6` then `openrouter/anthropic/claude-haiku-4-5-20251001` (tool calls, minimal reasoning)
- `extract` → `openrouter/anthropic/claude-sonnet-4-6` then `openrouter/anthropic/claude-haiku-4-5-20251001` (bulk fetch + summarize)
- `dashboard` → `openrouter/anthropic/claude-sonnet-4-6` then `openrouter/anthropic/claude-haiku-4-5-20251001` (HTML template generation)
- `scope` → `openrouter/anthropic/claude-sonnet-4-6` (query planning may not need Opus)
- `synthesize-report` → `openrouter/anthropic/claude-sonnet-4-6` (writing quality vs cost tradeoff)
- `synthesize-data` → `openrouter/anthropic/claude-sonnet-4-6` then `openrouter/anthropic/claude-haiku-4-5-20251001` (structured JSON extraction, may not need Opus)

---

## Common Pitfalls

1. **Silent model fallback.** Always check `modelApplied` after every spawn. Additionally verify the `MODEL_USED:` line. Abort on any mismatch.

2. **`mode="run"` is context-isolated.** Each child starts fresh with only the `task` string. Always use `mode="run"`, never `mode="session"`.

3. **Don't retry a failed step on a different model.** Defeats routing-evaluation purpose. Fail loudly.

4. **Rate limits on web_search and web_fetch.** Steps 2 and 3 must execute searches/fetches sequentially, not in parallel bursts. The step prompts explicitly instruct this.

5. **web_fetch failures are expected.** Some URLs will 403, timeout, or return garbage. The extract step is designed to record failures and continue. Don't abort the whole run for individual fetch failures.

6. **Synthesize is two steps.** Phase 5a (synthesize-report) outputs markdown only. Phase 5b (synthesize-data) outputs JSON only. The orchestrator must JSON-parse synthesize-data output and abort if invalid. Never combine these into a single call — the split exists to prevent output truncation.

6b. **Dashboard must ALWAYS be a subagent.** Never fall back to the orchestrator generating HTML directly. If synthesize-data JSON is invalid, abort the entire run. If the dashboard subagent fails, abort. The "no retries on different models / fail loudly" policy extends to "no fallback to orchestrator".

7. **HTML file size.** The dashboard should be under 50KB. If the dashboard step returns massive HTML, it may have included raw source text. The prompt constrains this but verify.

8. **Canvas availability.** If no Eragon nodes are connected, the dashboard HTML can still be written to the workspace and opened in a browser manually, or presented via the webchat canvas. Check `nodes status` first.

9. **Subagent timeout.** Phase 3 (extract) can run long on many sources. Keep `runTimeoutSeconds=600` on every step.

10. **Source deduplication.** The search step deduplicates by URL. But different URL formats can point to the same content (http vs https, trailing slashes, query params). The search step should normalize URLs before dedup.

---

## Verification Checklist

- [ ] Every `sessions_spawn` passes `model` from the routing table.
- [ ] Every `sessions_spawn` uses `mode="run"`.
- [ ] After each spawn, `modelApplied` is checked — `false` aborts.
- [ ] After each spawn, `MODEL_USED:<model>` line is verified — mismatch aborts.
- [ ] No step retries on a different model after failure.
- [ ] No fallback to orchestrator performing any step's work (especially dashboard HTML).
- [ ] Schema validation passes for every step before proceeding to the next.
- [ ] Routing Audit footer appended to final reply.
- [ ] All 7 subagents completed without error (scope, search, extract, analyze, synthesize-report, synthesize-data, dashboard).
- [ ] synthesize-report output contains required markdown headings.
- [ ] synthesize-data output is valid JSON with all required keys.
- [ ] scope output includes non-empty `bias_watchlist`.
- [ ] analyze confidence ratings are differentiated (not all the same value).
- [ ] Each step received ONLY its declared upstream inputs (strict input scoping).
- [ ] Dashboard HTML is valid, self-contained, under 50KB.
- [ ] Dashboard HTML written to workspace file.
- [ ] Canvas presented (if nodes available) or file path communicated.
- [ ] Markdown report includes source citations.
- [ ] No source was fabricated — all URLs came from actual web_search results.