# Benchmark Spec: deep-research

## Metadata

```yaml
workflow: deep-research
version: 1.0.0
requires_setup: false
parallelizable: true
parallel_reason: "Stateless workflow — only input is a research topic string. No shared external state. All 15 runs (3 methods × 5 runs) can execute concurrently."
steps_evaluated: [scope, search, extract, analyze, synthesize-report, synthesize-data, dashboard]
runs_per_method: 5
```

## Methods Under Comparison

| Method ID          | Description                                                                                         | Model(s)                                                           | Routing Table Used? |
|--------------------|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------|---------------------|
| `cowork`           | Claude Cowork (no routing). Single model, no per-step routing.                                      | `openrouter/anthropic/claude-sonnet-4.6` via `openrouter` provider | NO                  |
| `eragon-norouting` | Eragon all-Opus baseline. Forces every step to Opus — no routing table.                             | `anthropic/claude-opus-4.6` via `anthropic` provider               | NO (all-Opus)       |
| `eragon-routing`   | Eragon with routing. Uses the per-step routing table from `skill.md` (cost-optimized mix).          | Per routing table in `skill.md`                                    | YES                 |

**Rationale for all-Opus baseline:** `eragon-norouting` establishes a quality ceiling. The judge grades all other methods against this ceiling to determine whether cheaper routing degrades output quality per step.

## Setup Requirements

`requires_setup: false` — This workflow is stateless. Each run requires only a well-defined research topic string as input. No external accounts, OAuth, or inbox state is needed.

**Recommended test topics for the 5 runs:**
1. "The current state and near-term outlook for solid-state battery technology"
2. "How AI coding assistants are changing software developer productivity (2024–2025)"
3. "Carbon capture technology: costs, scalability, and deployment status"
4. "The competitive landscape of vector database systems for AI applications"
5. "Gene therapy for rare diseases: regulatory progress and commercial outcomes"

These topics are chosen to test: factual depth, source diversity, conflicting evidence, quantitative data extraction, and structured report synthesis.

## Teardown

No teardown required. Each run writes only to its local run directory. No external state is mutated.

## Parallelism

`parallelizable: true`

All 15 runs (5 runs × 3 methods) may be launched concurrently. There is no shared mutable state between runs — each run only requires a research topic string and writes to its own isolated run directory. The orchestrator should use ThreadPoolExecutor with max 5 workers to avoid overwhelming the LLM API.

## Rubric: D1–D4 (1–5 per dimension, /20 per step)

| Dimension | Code | Description                                                                                                  | Score 1 (Fail)                                   | Score 3 (Adequate)                                        | Score 5 (Excellent)                                                |
|-----------|------|--------------------------------------------------------------------------------------------------------------|--------------------------------------------------|-----------------------------------------------------------|--------------------------------------------------------------------|
| Correctness       | D1 | Output is factually accurate; no hallucinated URLs, statistics, source titles, or claims.                    | Multiple fabricated facts or URLs                | Mostly accurate; minor unsupported claims                 | Fully grounded; all URLs real; statistics cited with sources       |
| Completeness      | D2 | All required output fields present; no silent drops of queries, sources, or sub-questions.                   | Missing >20% of required fields or content       | Most required content present; minor omissions            | All required fields populated; query counts match depth setting    |
| Format Adherence  | D3 | Output matches the exact JSON schema or markdown structure specified in the step prompt.                     | Wrong format or unparseable                      | Parseable but deviations (missing/extra keys, wrong types)| Exact schema; all required keys present; types correct             |
| Faithfulness      | D4 | Each step uses only its declared upstream inputs; no invented context or out-of-scope upstream data injected. | Fabricates upstream data or invents source facts | Mostly faithful; minor unsupported inferences             | Strictly scoped to declared upstream inputs; `[UNCERTAIN]` on gaps |

**Per-step score:** D1 + D2 + D3 + D4 = /20
**Run total:** sum across all 7 evaluated steps = /140

## Steps Evaluated

### Step `scope` (Phase 1)
- **D1 Correctness:** Are the generated sub-questions and search queries coherent and on-topic? No nonsensical or off-topic queries.
- **D2 Completeness:** Do query counts match the requested depth (quick≈5, standard≈10, deep≈20)? Are `bias_watchlist` items populated with topic-specific biases (not generic placeholders)?
- **D3 Format Adherence:** Output matches `{core_question, sub_questions: [{id, question, queries, desired_source_types}], bias_watchlist, total_queries}`?
- **D4 Faithfulness:** Output based only on the user's research topic; no assumed external context.

### Step `search` (Phase 2)
- **D1 Correctness:** Are the URLs plausibly real (valid URL format, domain appropriate to topic)? Snippets match the stated URL domain?
- **D2 Completeness:** Were queries from `scope.output` actually executed? Did results respect the `max_sources` cap? Were results deduplicated by URL?
- **D3 Format Adherence:** Output matches `{results: [{url, title, snippet, related_sub_questions}], total_unique, queries_executed}`?
- **D4 Faithfulness:** Search queries derived from `scope.output` only; no additional queries invented out of scope.

### Step `extract` (Phase 3)
- **D1 Correctness:** Source summaries accurately represent the content at the URL (where verifiable). No hallucinated quotes or facts attributed to sources.
- **D2 Completeness:** Were all URLs from `search.output` attempted? Were failed extractions recorded in `failed_urls[]`? Are `key_facts` and `key_quotes` populated?
- **D3 Format Adherence:** Output matches `{sources: [{url, title, author, date, summary, key_facts, key_quotes, credibility, related_sub_questions}], failed_urls, total_extracted}`?
- **D4 Faithfulness:** Extraction based only on `scope.output` + `search.output`; no invented sources beyond what was returned by search.

### Step `analyze` (Phase 4)
- **D1 Correctness:** Consensus views are grounded in cited sources. Confidence ratings are differentiated (not all the same level) and justified by evidence quality.
- **D2 Completeness:** Does every sub-question from `scope.output` have an answer entry? Are themes, contradictions, and key_statistics populated?
- **D3 Format Adherence:** Output matches `{answers: [{sub_question_id, question, consensus, supporting_sources, dissenting_views, confidence}], themes, contradictions, evidence_quality, key_statistics}`?
- **D4 Faithfulness:** Analysis based only on `scope.output` + `extract.output`; no invented sources or unsupported statistics.

### Step `synthesize-report` (Phase 5a)
- **D1 Correctness:** Report claims are traceable to the analysis. Source citations (`[Source: url]`) reference real URLs from `extract.output`. No fabricated findings.
- **D2 Completeness:** All required sections present: `## Executive Summary`, `## Key Findings`, `## Sources`. 5–8 key findings. Statistics section populated.
- **D3 Format Adherence:** Output is plain markdown (no fences). Contains exactly the required headings. No JSON or DASHBOARD_DATA appended.
- **D4 Faithfulness:** Report synthesizes only `scope.output` + `analyze.output`; no facts from steps not in declared upstream.

### Step `synthesize-data` (Phase 5b)
- **D1 Correctness:** Counts (`finding_count`, `source_count`, confidence counts) match the actual lengths of their respective arrays. All URLs in `sources[]` are real URLs from the analysis.
- **D2 Completeness:** All required top-level keys present: `topic`, `executive_summary`, `finding_count`, `source_count`, `high_confidence_answers`, `medium_confidence_answers`, `low_confidence_answers`, `key_findings`, `key_stats`, `themes`, `contradictions`, `evidence_quality`, `sources`.
- **D3 Format Adherence:** Output is pure JSON (no markdown, no fences, no prose). JSON is parseable. All required keys present with correct types.
- **D4 Faithfulness:** JSON extracted from `scope.output` + `analyze.output` + `synthesize-report.output` only; no invented data.

### Step `dashboard` (Phase 6)
- **D1 Correctness:** Dashboard data matches the JSON provided in `synthesize-data.output`. Stat counts, finding titles, and source URLs rendered accurately.
- **D2 Completeness:** All 8 required dashboard sections present: header, stats bar, key findings, key stats, themes, contradictions, evidence quality, sources.
- **D3 Format Adherence:** Output starts with `<!DOCTYPE html>` and ends with `</html>`. File is self-contained (no external dependencies). Under 50KB. Interactive features (expand/collapse, confidence filter) implemented.
- **D4 Faithfulness:** Dashboard renders only data from `synthesize-data.output`; no additional facts injected by the dashboard step.

## Judge Instructions

You are an LLM judge evaluating the output of a deep-research benchmark. You will receive:
1. This spec (rubric, step definitions, method descriptions)
2. The full `output.txt` from a single run
3. The `run.json` metadata (method, run_id, timestamp, topic)

**Scoring procedure:**

For each of the 7 steps (`scope`, `search`, `extract`, `analyze`, `synthesize-report`, `synthesize-data`, `dashboard`):

1. Locate the step's output in `output.txt` (look for `MODEL_USED:` lines as step boundaries, or step output markers).
2. Score D1, D2, D3, D4 each on a 1–5 integer scale using the rubric above.
3. For each dimension score, provide 1–2 sentences of **evidence** quoting specific output fragments that justify the score.
4. Compute the step total: D1 + D2 + D3 + D4 (max 20).

**Comparison guidance:**
- When scoring all 3 methods on the same research topic, evaluate each independently first, then note relative differences.
- Do NOT inflate scores because a step used a cheaper model — grade only on output quality.
- The `eragon-norouting` all-Opus run is the quality ceiling; note when cheaper-model steps match or fall short of it.
- Flag schema validation failures (e.g., `synthesize-data` not parseable as JSON) as D3=1 regardless of content quality.

**Output format (strict JSON, no fences):**
```json
{
  "run_id": "...",
  "method": "...",
  "topic": "...",
  "step_scores": {
    "scope":             {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "search":            {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "extract":           {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "analyze":           {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "synthesize-report": {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "synthesize-data":   {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}},
    "dashboard":         {"D1": N, "D2": N, "D3": N, "D4": N, "total": N, "evidence": {"D1": "...", "D2": "...", "D3": "...", "D4": "..."}}
  },
  "run_total": N,
  "judge_notes": "..."
}
```
