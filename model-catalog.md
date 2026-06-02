# Model Catalog

Verified via OpenRouter API, May 2026. All prices per million tokens.

| # | Catalog Name | OpenRouter ID | Input $/M | Output $/M | Cache Read $/M | Cache Write $/M | Caching |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | claude-opus-4.8 | anthropic/claude-opus-4.8 | $5.000 | $25.000 | $0.500 | $6.250 | YES |
| 2 | gpt-5.5 | openai/gpt-5.5 | $5.000 | $30.000 | $0.500 | — | YES |
| 3 | claude-sonnet-4.6 | anthropic/claude-sonnet-4.6 | $3.000 | $15.000 | $0.300 | $3.750 | YES |
| 4 | qwen3.7-max | qwen/qwen3.7-max | $1.250 | $3.750 | $0.250 | $1.563 | YES |
| 5 | gemini-3.5-flash | google/gemini-3.5-flash | $1.500 | $9.000 | $0.150 | $0.083 | YES |
| 6 | grok-4.3 | x-ai/grok-4.3 | $1.250 | $2.500 | $0.200 | — | YES (read-only) |
| 7 | deepseek-v4-pro | deepseek/deepseek-v4-pro | $0.435 | $0.870 | $0.004 | — | YES (read-only) |
| 8 | kimi-k2.6 | moonshotai/kimi-k2.6 | $0.730 | $3.490 | $0.250 | — | YES (read-only) |
| 9 | minimax-m2.7 | minimax/minimax-m2.7 | $0.279 | $1.200 | — | — | NO |
| 10 | ring-2.6-1t | inclusionai/ring-2.6-1t | $0.075 | $0.625 | $0.015 | — | YES (read-only) |

Notes:
- Full cache (read+write): claude-opus-4.8, claude-sonnet-4.6, qwen3.7-max, gemini-3.5-flash
- Cache read only (automatic): grok-4.3, deepseek-v4-pro, kimi-k2.6, ring-2.6-1t, gpt-5.5
- No caching: minimax-m2.7
- Ignore original Status column; all 10 are valid routing candidates
