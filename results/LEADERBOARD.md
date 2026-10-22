# zbench leaderboard (snapshot 2026-10-20)

Model, harness, and how many of the shared tasks each run resolved. Hosting (cloud API vs self-hosted) is not a factor in the table. The same model appears once per harness, because the harness (the agent program driving the model) changes the result.

| # | Model | Harness | Resolved | Rate |
|---|---|---|---|---|
| 1 | Claude Opus 5 | Claude Code | 101 / 107 | 94.4% |
| 2 | Claude Opus 5 | pi | 100 / 107 | 93.5% |
| 3 | Claude Fable 5 | pi | 100 / 107 | 93.5% |
| 4 | Claude Fable 5 | Claude Code | 98 / 107 | 91.6% |
| 5 | GPT-5.6 Sol | pi | 94 / 107 | 87.9% |
| 6 | GPT-5.6 Sol | Codex | 93 / 107 | 86.9% |
| 7 | Claude Opus 4.8 | Claude Code | 92 / 107 | 86.0% |
| 8 | GLM-5.3 Flash * | Claude Code | 92 / 107 | 86.0% |
| 9 | GPT-5.6 Terra | Codex | 91 / 107 | 85.0% |
| 10 | Claude Opus 4.8 | pi | 91 / 107 | 85.0% |
| 11 | GPT-5.6 Luna | Codex | 88 / 107 | 82.2% |
| 12 | Claude Sonnet 4.6 | Claude Code | 87 / 107 | 81.3% |
| 13 | GPT-5.6 Terra | pi | 86 / 107 | 80.4% |
| 14 | Claude Sonnet 4.6 | pi | 85 / 107 | 79.4% |
| 15 | Muse Glimmer 30B | pi | 83 / 107 | 77.6% |
| 16 | GPT-5.6 Luna | pi | 80 / 107 | 74.8% |
| 17 | Claude Haiku 4.5 | Claude Code | 74 / 107 | 69.2% |
| 18 | Qwen3.6 27B | pi | 68 / 107 | 63.6% |
| 19 | Claude Haiku 4.5 | pi | 64 / 107 | 59.8% |
| 20 | gpt-oss 120B | pi | 63 / 107 | 58.9% |
| 21 | Gemma 4 31B | pi | 60 / 107 | 56.1% |
| 22 | Nemotron 3.5 Lightning 30B-A3B | pi | 40 / 107 | 37.4% |

\* Run separately from the 21-model grid. It ran all 107 tasks of its own shared set, which differs from the grid's set by 3 tasks, so compare it with care.

Machine-readable: [`leaderboard.csv`](leaderboard.csv). Costs, tokens, turns and per-task outcomes: [`per_model_summary.csv`](per_model_summary.csv), [`per_task_results.csv`](per_task_results.csv); see [`README.md`](README.md) for how these were computed.
