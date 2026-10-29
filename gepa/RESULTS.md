# GEPA proof of concept: results

Status as of 2026-10-29 12:00 PDT. Owner: Robert. Branch `gepa` (uncommitted).

## Setup

- **Method.** GEPA (arXiv 2507.19457): reflective prompt evolution with Pareto selection.
  The optimized component is only `PI_APPEND_SYSTEM_PROMPT` (text appended to the pi
  harness system prompt). The seed (empty text) is the baseline. One prompt per model.
- **Reflection model.** Claude Opus 5.5 (headless `claude -p`).
- **Tasks.** 20 validation tasks (GEPA optimizes on these) and 30 held-out test tasks
  (never seen by GEPA). Hard tasks: the board baseline solved 0-4 of 5 models.
  Lists in `gepa/tasks.json`.
- **Model settings.** Original board settings for every model (pi harness, same thinking
  level, same timeouts). Only the appended prompt changes.
- **Versions.**
  - **v1** (`gepa_run.py`, `runs/`): score = resolved (0/1), 1 sample, reflector sees
    traces + failing test names + error excerpt.
  - **v2** (`gepa_run_v2.py`, `runs-v2/`): (A) reflector also sees the reference fix and
    the hidden test diff (agent never sees them); (B) partial credit = 0.5 x fraction of
    fail_to_pass tests that pass; (C) 3 samples per (prompt, task), minibatch 6.
    Budget 240 metric calls. Haiku 4.5 v2 ran with a "600 words" line in the reflection
    template (`runs-v2/pi-anthropic-haiku-4-5`); all other v2 runs are without it
    (`runs-v2-nolimit/` for the Haiku 4.5 rerun).
  - **cost-aware** (`gepa_run_cost.py`, `runs-cost/`): v2 + score =
    partial - 0.1 x min(cost / seed_cost, 3), per task; reflector sees costs.
- **Statistics.** Held-out: per-task mean resolve over samples, paired sign-flip
  permutation test (two-sided). Cost: geometric mean over tasks of cost(new)/cost(seed),
  sign-flip test on log ratios. About 22% of per-task outcomes flip between two identical
  runs, so single-sample differences of 1-3 tasks are noise.
- **Cost.** `tools/model_prices.cost_usd`; open-weight models at a public-host per-token
  price (reference price, not our GPU cost). Haiku 5.5 uses per-request tiered pricing
  from the session files (prompt > 100K tokens = 5x per token); pi itself reports only the
  low tier, which under-reports Haiku 5.5 cost by about 2.5x. Wall-clock time is not used
  (confounded by server load).

## Summary

1. **Resolve rate.** No GEPA prompt improved the held-out resolve rate significantly for
   any model (all p >= 0.14). Validation gains (+0.08 to +0.20) did not carry over. This
   matches selection on noise (winner's curse) with 20 validation tasks.
2. **Cost.** Prompts optimized only for accuracy did not cut held-out cost for Haiku 4.5,
   Luna v1, Gemma, Qwen v1 or Muse (ratios 0.95-1.14). For Haiku 5.5 they did (0.78x,
   p=0.04), for gpt-oss-120b (0.80x, p=0.04) and for Qwen v2 (0.77x, p<0.01).
3. **Cost-aware GEPA on Haiku 5.5** cut held-out cost to 0.33x seed (29 of 30 tasks
   cheaper, p<0.001; $0.132 -> $0.030 per run). With 6 samples (2026-10-27): cost
   0.30x (30/30 tasks cheaper, $0.151 -> $0.031), resolve 0.823 -> 0.767 (-0.057,
   p=0.26, 95% CI [-0.151, +0.027]). No significant loss, but non-inferiority at a
   10-point margin is NOT shown (lower CI bound -0.151 < -0.10).
3b. **Cost-aware GEPA on GPT-5.6 Luna** (2026-10-28) cut held-out cost to 0.57x seed
   (30/30 tasks cheaper, $0.084 -> $0.051 per run, turns 0.59x). Resolve 0.678 -> 0.711
   (+0.033, 95% CI [-0.022, +0.100]): non-inferiority at a 10-point margin IS shown.
   This is the first run where the cost fell and the resolve rate is shown to hold.
   Luna's accuracy-only v1 prompt did not change cost (1.04x).
3c. **GPT-5.6 Sol** (held-out done 2026-10-29 11:50). Cost-aware cut held-out cost to
   0.58x seed (95% CI [0.55, 0.62], 30/30 tasks cheaper, $1.96 -> $1.14 per run, turns
   0.60x). v2 accuracy-only: 0.86x [0.79, 0.92], turns 0.74x. Resolve 0.789 -> 0.744
   (cost-aware, -0.044, CI [-0.156, +0.067], p=0.59) and -> 0.733 (v2, -0.056,
   CI [-0.133, +0.022], p=0.31). No significant loss, but non-inferiority at a 10-point
   margin is NOT shown for either prompt. $ per resolve 2.49 -> 1.53 (cost-aware).
4. **Thesis check.** Robert's thesis was that smaller models gain more from prompt
   optimization. The data do not support it for resolve rate. Cost is the axis where
   GEPA moved a model on the Pareto frontier.

## Held-out resolve rate (30 tasks)

x/30 = 1 sample (Luna and Qwen, v1 test only). x/90 = 3 samples (all arms re-run in the
v2 held-out test, including seed and v1 best). "Board" = the model's original board run
on the same 30 tasks.

| Model | Board | Seed | v1 best | v2 best | Cost-aware | p (vs seed) |
|---|---|---|---|---|---|---|
| GPT-5.6 Luna | 16/30 | 19/30; 3 samples 61/90 (0.678) | 19/30; 3 samples 55/90 (0.611) | 57/88 (0.644, mean of task rates) | 64/90 (0.711) | v1 1.0 (3s: 0.34); v2 0.53; cost 0.53 |
| Haiku 4.5 | 8/30 | 41/90 (0.456) | 39/90 (0.433) | limit600: 35/90 (0.389); no limit: 39/90 (0.433) | - | v1 0.85; v2-limit 0.34; v2 0.88 |
| Haiku 5.5 | - | 73/90 (0.811); 6 samples 148/179 (0.823) | - | 76/90 (0.844) | 69/90 (0.767); 6 samples 138/180 (0.767) | v2 0.50; cost 0.49; cost 6s 0.26 |
| GPT-5.6 Sol | - | 71/90 (0.789) | - | 66/90 (0.733) | 67/90 (0.744) | v2 0.31; cost 0.59 |
| Muse Glimmer 30B | 21/30 | 48/90 (0.533) | 53/90 (0.589) | 51/90 (0.567) | - | v1 0.47; v2 0.73 |
| Gemma 4 31B | 9/30 | 41/90 (0.456) | 33/90 (0.367) | 38/90 (0.422) | - | v1 0.14; v2 0.64 |
| Qwen3.6 27B | 7/30 | 15/30; 3 samples 43/90 (0.478) | 10/30; 3 samples 39/90 (0.433) | 44/90 (0.489) | - | v1 0.18 (3s: 0.53); v2 1.0 |
| gpt-oss-120b | - | 36/90 (0.400) | - | 41/90 (0.456) | - | v2 0.45 |

gpt-oss-120b v2 resolve difference vs seed: +0.056, bootstrap 95% CI [-0.056, +0.167],
p=0.45, tasks up/down 12/6.

Qwen3.6 27B (held-out done 2026-10-29 05:03, 0 infra failures; ran on one replica after
00:00): v2 vs seed +0.011, bootstrap 95% CI [-0.111, +0.133], p=1.0, tasks up/down 9/7.
v1 vs seed (3 samples) -0.044 [-0.144, +0.056], p=0.53. Validation gain 0.525 -> 0.771 did
not carry over. v2 cost 0.77x, 95% CI [0.66, 0.89], 21/30 tasks cheaper, turns 0.82x.

GPT-5.6 Luna cost-aware (2026-10-28), 3 samples: resolve +0.033, bootstrap 95% CI
[-0.022, +0.100], p=0.53, tasks up/down 4/2 -> NON-INFERIORITY SHOWN at a 10-point margin
(lower bound -0.022 > -0.10). Cost 0.57x, 95% CI [0.51, 0.63], 30/30 tasks cheaper,
turns 0.59x. v1 best on 3 samples: -0.067 [-0.178, +0.022], cost 0.99x.
Luna v2 accuracy-only: -0.033 [-0.144, +0.067], cost 0.89x [0.79, 0.99], turns 0.86x
(2 cells lost to the OpenAI spend limit at 18:34). So most of Luna's cost saving comes
from the cost objective, not from the v2 setup.

GPT-5.6 Sol (2026-10-29, 3 samples, 0 infra failures; seed cells shared by both arms):
v2 -0.056 [-0.133, +0.022], p=0.31, tasks up/down 2/7, cost 0.86x [0.79, 0.92], turns
0.74x. Cost-aware -0.044 [-0.156, +0.067], p=0.59, tasks up/down 3/5, cost 0.58x
[0.55, 0.62], 30/30 tasks cheaper, turns 0.60x. Held-out seed cost $1.96 per run (validation
$1.52). Same pattern as Luna: the cost objective gives most of the saving.

Haiku 5.5 resolve difference vs seed, bootstrap 95% CI over tasks:
v2 accuracy-only +0.033 [-0.022, +0.089]; cost-aware -0.044 [-0.133, +0.044].
Cost-aware vs accuracy-only: -0.078, p=0.12.
Cost-aware, 6 samples (seed and cost-aware only; 1 seed cell lost to a worktree error):
samples 4-6 alone -0.067 [-0.189, +0.044]; samples 1-6 -0.057 [-0.151, +0.027], p=0.26,
tasks up/down 4/6. The loss is concentrated in 3 tasks that seed solves 6/6 or 5/6 and
cost-aware solves 1-2/6 (ZT-4d5abdae1c10, ZT-afb960c04137, ZT-b7ce31135d20).

## Validation score (20 tasks, what GEPA optimized)

v1 = resolve rate (1 sample). v2 / cost-aware = mean partial-credit score (3 samples;
cost-aware includes the cost term, so it is not comparable to v2).

| Model | Run | Seed | Best | Best idx / candidates | Best prompt words | Metric calls |
|---|---|---|---|---|---|---|
| GPT-5.6 Luna | v1 | 0.700 | 0.800 | 1 / 5 | 594 | 220 |
| Haiku 4.5 | v1 | 0.650 | 0.750 | 6 / 7 | 594 | 209 |
| Haiku 4.5 | v2 limit600 | 0.608 | 0.725 | 2 / 6 | 645 | 240 |
| Haiku 4.5 | v2 no limit | 0.608 | 0.698 | 4 / 7 | 1301 | 248 |
| Haiku 5.5 | v2 | 0.840 | 0.917 | 2 / 5 | 1137 | 256 |
| Haiku 5.5 | cost-aware | 0.740 | 0.795 | 3 / 8 | 420 | 268 |
| GPT-5.6 Luna | v2 | 0.781 | 0.872 | 2 / 6 | 662 | 240 |
| GPT-5.6 Luna | cost-aware | 0.681 | 0.791 | 4 / 6 | 658 | 240 |
| GPT-5.6 Sol | v2 | 0.819 | 0.877 | 3 / 6 | 1179 | 240 |
| GPT-5.6 Sol | cost-aware | 0.719 | 0.815 | 6 / 7 | 918 | 242 |
| Muse Glimmer 30B | v1 | 0.600 | 0.800 | 4 / 6 | 689 | 201 |
| Muse Glimmer 30B | v2 | 0.731 | 0.831 | 1 / 6 | 752 | 264 |
| Gemma 4 31B | v1 | 0.400 | 0.600 | 4 / 7 | 654 | 209 |
| Gemma 4 31B | v2 | 0.508 | 0.633 | 3 / 8 | 742 | 256 |
| Qwen3.6 27B | v1 | 0.500 | 0.650 | 5 / 6 | 582 | 216 |
| Qwen3.6 27B | v2 | 0.525 | 0.771 | 6 / 7 | 1633 | 248 |
| gpt-oss-120b | v2 | 0.554 | 0.723 | 5 / 7 | 1353 | 260 |

## Held-out cost (30 tasks)

Cost per run = mean over tasks. Ratio = geometric mean over tasks of new/seed;
v/^ = number of tasks cheaper / more expensive. Turns = model round-trips.

| Model | Prompt | Cost per run seed -> new | Cost ratio | p | Tasks v/^ | Turns ratio | p (turns) |
|---|---|---|---|---|---|---|---|
| GPT-5.6 Luna | v1 | $0.082 -> $0.089 | 1.04 | 0.58 | 13/16 | 0.98 | 0.73 |
| GPT-5.6 Luna | v2 | $0.083 -> $0.078 | 0.86 | 0.05 | 17/13 | 0.84 | 0.02 |
| GPT-5.6 Luna | cost-aware | $0.083 -> $0.051 | **0.58** | <0.001 | 29/1 | 0.60 | <0.001 |
| GPT-5.6 Sol | v2 | $1.962 -> $1.724 | 0.86 | <0.01 | 22/8 | 0.74 | <0.01 |
| GPT-5.6 Sol | cost-aware | $1.962 -> $1.141 | **0.58** | <0.01 | 30/0 | 0.60 | <0.01 |
| Haiku 4.5 | v1 | $0.560 -> $0.577 | 1.03 | 0.47 | 11/19 | 1.01 | 0.80 |
| Haiku 4.5 | v2 limit600 | $0.581 -> $0.618 | 1.06 | 0.02 | 11/19 | 1.04 | 0.15 |
| Haiku 4.5 | v2 no limit | $0.581 -> $0.598 | 1.03 | 0.29 | 12/18 | 0.99 | 0.55 |
| Haiku 5.5 | v2 | $0.132 -> $0.099 | 0.78 | 0.04 | 21/9 | 0.72 | <0.001 |
| Haiku 5.5 | cost-aware | $0.132 -> $0.030 | **0.33** | <0.001 | 29/1 | 0.55 | <0.001 |
| Muse Glimmer 30B | v1 | $0.157 -> $0.182 | 1.13 | 0.07 | 12/18 | 1.03 | 0.63 |
| Muse Glimmer 30B | v2 | $0.167 -> $0.162 | 0.95 | 0.21 | 19/11 | 0.92 | 0.02 |
| Gemma 4 31B | v1 | $0.043 -> $0.044 | 1.14 | 0.17 | 11/19 | 1.05 | 0.48 |
| Gemma 4 31B | v2 | $0.050 -> $0.049 | 1.08 | 0.25 | 12/18 | 1.27 | <0.001 |
| Qwen3.6 27B | v1 | $1.029 -> $0.990 | 0.96 | 0.55 | 16/14 | 0.87 | 0.01 |
| Qwen3.6 27B | v2 | $1.010 -> $0.830 | **0.77** | <0.01 | 21/9 | 0.82 | <0.01 |
| gpt-oss-120b | v2 | $0.556 -> $0.412 | 0.80 | 0.04 | 22/8 | 1.01 | 0.91 |

Table values come from `analysis/cost.txt` (store-based; the Luna text above uses the
test_eval cells, so it differs by 0.01-0.03).
Cost per resolve, Haiku 5.5: seed $0.16, v2 $0.12, cost-aware $0.04.
Haiku 5.5 cost-aware, 6 samples (tiered): $0.151 -> $0.031 per run, geometric-mean ratio
0.30, bootstrap 95% CI [0.24, 0.36], 30/30 tasks cheaper. Samples 4-6 alone: 0.28.
gpt-oss cost: public-host per-token reference price; $ per resolve 1.39 -> 0.90. Fewer
tokens per run (0.79x), same number of turns (1.01x).
Qwen cost is high because its prefix-cache hit rate is 0% (hybrid attention).

### Validation cost (all candidates vs seed, 20 tasks)

GEPA did not select on cost in v1/v2, but the reflector saw the validation reference
fixes (v2), so validation cost can be optimistic.

| Model | Run | Cost ratio range over candidates | Candidates with p<0.05 |
|---|---|---|---|
| GPT-5.6 Luna | v1 | 0.97-1.12 | 0/4 |
| GPT-5.6 Luna | v2 | 0.80-0.99 | 3/5 |
| GPT-5.6 Luna | cost-aware | 0.47-0.58 | 5/5 |
| GPT-5.6 Sol | v2 | 0.73-0.80 | 5/5 |
| GPT-5.6 Sol | cost-aware | 0.53-0.63 | 6/6 |
| Haiku 4.5 | v1 | 0.90-1.23 | 2/6 |
| Haiku 4.5 | v2 limit600 | 0.89-1.03 | 1/5 |
| Haiku 4.5 | v2 no limit | 0.91-1.01 | 2/6 |
| Haiku 5.5 | v2 | 0.72-0.87 | 3/4 |
| Haiku 5.5 | cost-aware | 0.37-0.52 | 7/7 |
| Muse Glimmer 30B | v1 | 0.89-1.09 | 0/5 |
| Muse Glimmer 30B | v2 | 0.75-0.83 | 5/5 |
| Gemma 4 31B | v1 | 0.64-1.33 | 2/6 |
| Gemma 4 31B | v2 | 0.73-0.96 | 1/7 |
| Qwen3.6 27B | v1 | 0.77-1.43 | 1/5 |
| Qwen3.6 27B | v2 | 0.71-0.87 | 2/6 |
| gpt-oss-120b | v2 | 0.53-0.67 | 6/6 |

Carry-over to held-out: Muse v2 0.75-0.83 on validation -> 0.95 held-out (mostly lost);
Gemma v2 0.73-0.96 -> 1.08 (lost; Gemma used 27% MORE turns on held-out);
Haiku 5.5 v2 0.77 -> 0.78 (kept); Haiku 5.5 cost-aware 0.37-0.52 -> 0.33 (kept);
Luna v2 0.80-0.99 -> 0.89 (kept); Luna cost-aware 0.47-0.58 -> 0.57 (kept);
gpt-oss v2 0.53-0.67 -> 0.80 (partly kept); Qwen v2 0.71-0.87 -> 0.77 (kept);
Sol v2 0.73-0.80 -> 0.86 (partly kept); Sol cost-aware 0.53-0.63 -> 0.58 (kept).
Sol validation detail (cost / turns / wall-clock vs seed): v2 cand1-5 0.74-0.80 /
0.61-0.65 / 0.51-0.60; cost-aware cand1-6 0.53-0.63 / 0.53-0.69 / 0.47-0.54.

## Why the Haiku 5.5 cost-aware prompt is cheaper

- Requests per run: 42 (seed) -> 22.
- Share of requests with a prompt > 100K tokens (5x price): 21% -> 1%.
- The prompt (420 words) asks for: read only line ranges (`grep -rn`, `sed -n`), no
  whole-file reads, short command outputs, no re-reading, reuse existing helpers, stop
  after one re-read of the diff. Full text: `runs-cost/pi-anthropic-haiku-5-5/summary.json`
  (`best_prompt`).

## Other findings

- **Agent sandbox has no Zulip dev env** (no virtualenv, node_modules, database, or
  `python`). Agents cannot run the Zulip test runners. v1 GEPA learned this for Luna,
  Gemma and Muse, not for Haiku 4.5. The v2 reflection template states it.
- **Dominant failure mode** for all models = wrong behavior (assertion failures), not
  crashes or missing patches.
- **29 of 50 tasks have a single fail_to_pass test**, so partial credit is mostly binary.
- **Prompt length.** Without the 600-word line, v2 prompts grew to 725-2050 words. Length
  did not predict held-out resolve.
- **Haiku 5.5 thinking limit.** Haiku 5.5 sometimes spends all 32K output tokens on
  thinking and makes no edit. A bug in `rollout_runner.is_valid_attempt` treated these as
  infra failures (2 GEPA iterations lost in the Haiku 5.5 v2 run); fixed 2026-10-26 before
  any held-out test. The 32K limit is the original pi setting and was not changed.
- **pi and Haiku 5.5.** pi did not know `claude-haiku-5-5`. Fixed with a custom model in
  `~/.pi/agent/models.json` and a one-line pi patch (adaptive thinking). See Environment.

## Open items

- Haiku 5.5 cost-aware 6-sample test: DONE 2026-10-27 (see above). Non-inferiority not
  shown. A cost weight of 0.05 may keep more resolves.
- Optional: cost-aware rerun with cost weight 0.05.
- Cost-aware GEPA on other models (the largest $ saving would be Qwen at $1.03 per run).
- Qwen v2 GEPA + held-out: DONE 2026-10-29 05:03. gpt-oss-120b done 2026-10-28 02:20.
- Sol runs: DONE 2026-10-29 11:50 after the OpenAI budget was raised (resumed 11:02;
  cost-aware GEPA finished at 242 calls, best unchanged). Spend-limit failures from
  2026-10-28 (142 cells, 0 tokens) were re-run; old log `runs-v2/.../test_eval.spendlimit-2026-10-28.log`.
- Candidates not tried: Nemotron. No larger Claude models
  (Robert, 2026-10-26).

## Environment changes to revert after the experiment

- `~/.pi/agent/models.json`: qwen baseUrl 8011 -> 8016 (load balancer; backup
  `models.json.bak-qwen-lb-2026-10-23`); Haiku 5.5 custom model added (backup
  `models.json.bak-haiku55-2026-10-26`). Muse baseUrl already restored to 8014.
- pi patch: `.../pi-ai/dist/providers/anthropic.js` `supportsAdaptiveThinking` +=
  `haiku-5-5` (backup `anthropic.js.bak-haiku55-2026-10-26`; a pi update removes it).
- Servers started for GEPA: second Qwen replica :8015 (GPUs 0,1; stopped 2026-10-29 00:00 for
  a teammate) + LB :8016; :8011 (GPUs 2,3) and the LB stopped 2026-10-29 09:14 (Qwen work done).
  Restart (from purebench/): `CUDA_VISIBLE_DEVICES=2,3 HF_HOME=/mnt/data/robert-scripts/hf-cache
  /mnt/data/robert-scripts/venvs/vllm/bin/vllm serve Qwen/Qwen3.6-27B --served-model-name
  qwen3.6-27b --host 127.0.0.1 --port 8011 --tensor-parallel-size 2 --gpu-memory-utilization 0.92
  --max-model-len 131072 --enable-auto-tool-choice --tool-call-parser qwen3_coder
  --reasoning-parser qwen3`, then `venvs/vllm/bin/python ../pure-swebench/gepa/lb_proxy.py`
  (pi models.json points qwen at :8016, the LB). gpt-oss-120b :8010 on
  GPUs 4,5 (stopped 2026-10-28 02:25). Gemma docker (GPUs 6,7) stopped 2026-10-27 (`--rm`, so restart with the
  original docker run command).

## Files

- Results per run: `gepa/runs*/<agent>/{summary.json, test_eval.json, candidates.json}`.
  Extra arms: `runs-v2-nolimit/pi-anthropic-haiku-4-5/test_eval.json` (4 arms),
  `runs-cost/pi-anthropic-haiku-5-5/test_eval.json` (seed + cost-aware, 6 samples);
  `runs-cost/pi-anthropic-haiku-5-5/test_eval.3arm-3samples.json` (seed, cost-aware, v2
  accuracy-only, 3 samples).
- Cost analysis: `gepa/analysis/cost_analysis.py` -> `cost.json`, `cost.txt`. Rerun:
  `gepa/.venv/bin/python gepa/analysis/cost_analysis.py gepa/analysis/cost.json > gepa/analysis/cost.txt`
- Private result store: `gepa/store/bench.db` (never the main purebench `bench.db`).
