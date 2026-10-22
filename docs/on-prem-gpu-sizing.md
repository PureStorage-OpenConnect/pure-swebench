# On-prem GPU sizing for the open-weight roster

How much GPU memory you need to self-host each open-weight model in the zbench
roster, on **NVIDIA H200** (141 GB HBM3e, Hopper, native FP8) and **NVIDIA B300**
(288 GB HBM3e, Blackwell Ultra, native FP8 and FP4/NVFP4). The arithmetic is shown so you
can size any other model the same way.

This is **generic sizing guidance, not a record of what was used to produce the shipped
results.** Treat every number as a planning estimate and confirm it with a real launch
(`tools/serving/serve_local.sh check`) before you commit a long run.

Related: [`running-your-models.md`](running-your-models.md) (how to wire a served model
into the harness), [`replicate-zbench.md`](replicate-zbench.md) (the end-to-end
replication), [`../tools/serving/README.md`](../tools/serving/README.md) (the serving
scripts and the traps we hit).

---

## 1. The arithmetic

```
weights_GB      = total_params_B x bytes_per_param
need_GB         = weights_GB x 1.10  +  4 x n_gpus  +  KV_cache_GB
usable_per_GPU  = HBM_GB x gpu_memory_utilization          (vLLM default 0.90;
                                                            serve_local.sh uses 0.92)
fits if         n_gpus x usable_per_GPU  >=  need_GB
```

| term | what it is | value used here |
|---|---|---|
| `bytes_per_param` | BF16 = 2.0, FP8 = 1.0, FP4 = 0.5 plus block scales (MXFP4 ~0.53, NVFP4 ~0.56) | per row below |
| x 1.10 | allowance for weight padding, unquantized layers (embeddings, norms, routers), CUDA graphs | a planning assumption, not a measurement |
| `4 x n_gpus` | per-GPU runtime buffers (NCCL, activation workspace) | a planning assumption; real value grows with `--max-num-batched-tokens` |
| `usable_per_GPU` | 141 x 0.92 = ~130 GB (H200); 288 x 0.92 = ~265 GB (B300) | |
| `KV_cache_GB` | see section 2 | whatever is left over is your KV budget |

**For MoE models the TOTAL parameter count sets memory** (every expert must be resident).
The ACTIVE parameter count sets speed (bytes read per generated token).

**Tensor-parallel (TP) size** must divide the model's attention-head count, so in practice
use 1, 2, 4 or 8 within a node. Beyond 8 GPUs you need multiple nodes (pipeline parallel
and a fast interconnect), which is a different operational project; the tables below say
"2 nodes" where that is what the arithmetic implies.

## 2. KV cache: the part people forget

Agent runs are long, multi-turn trajectories, so the KV cache, not the weights, often
decides how many tasks you can run in parallel.

```
KV_bytes_per_token = 2 (K and V) x n_layers x n_kv_heads x head_dim x bytes_per_element
KV_GB_per_sequence = KV_bytes_per_token x context_tokens / 1e9
```

Read `n_layers`, `n_kv_heads`, `head_dim` from the model's `config.json`. Worked example
with an **illustrative** (not any specific model's) config of 64 layers, 8 KV heads,
head_dim 128, BF16 cache:

```
2 x 64 x 8 x 128 x 2 bytes = 262,144 bytes/token  (0.25 MB)
x 131,072 tokens           = ~34 GB per full-length sequence
```

So with ~60 GB left for KV you hold roughly **one to two** full-context sequences of such a
model; with ~190 GB (one B300) roughly five to six. Models with multi-head latent
attention (MLA), sliding-window layers, or Mamba/SSM layers use far less per token, so
read the config rather than assuming. `--kv-cache-dtype fp8` halves KV memory at some
accuracy risk; if you use it, use it for every model you compare.

The zbench local rows pin `--max-model-len 131072` for every model
(`tools/serving/models.conf`; METHODOLOGY section 6 wants one context budget across
agents). The tables below use that context. Agent trajectories rarely fill the whole
window, so real concurrency is usually higher than the full-context arithmetic suggests;
the harness also compacts history near the limit.

## 3. The roster

Parameter counts come from the model cards linked in `zbench-tasks/agents-meta.jsonl`
(`hf_url`) and were read from those cards when this guide was written. **Check the card
yourself before purchasing hardware**; cards change, and "unknown" below means the card did
not state it.

### 3.1 Models the shipped agent rows serve locally

These are the five `pi-vllm-*` rows in `zbench-tasks/agents-matrix.jsonl` and the five
lines in `tools/serving/models.conf`.

| Model (served alias) | Total / active params | Shape | Card |
|---|---|---|---|
| gpt-oss-120b | ~117 B / 5.1 B | MoE; checkpoint ships in MXFP4 (MoE weights) | `openai/gpt-oss-120b` |
| qwen3.6-27b | 27 B / 27 B (card does not say "dense"; no expert routing described) | dense | `Qwen/Qwen3.6-27B` |
| nemotron-3.5-lightning-30b | 30 B / 3 B | MoE, Mamba-2 / attention hybrid | `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16` |
| gemma-4-31b | 30.7 B / 30.7 B | dense | `google/gemma-4-31B-it` |
| muse-glimmer-30b | ~29.6 B (incl. ~1.8 B vision encoder) / same | dense, multimodal | `meta-models/Muse-Glimmer-30B` |

Memory (weights x 1.10 = "w+10%"), and the minimum GPU count that leaves a workable KV
budget (about 55 GB or more):

| Model | Format | Weights | w+10% | H200 min (KV left) | B300 min (KV left) |
|---|---|---|---|---|---|
| gpt-oss-120b | MXFP4 as shipped (0.53 B/param) | ~62 GB | ~68 GB | 1 GPU (~58 GB KV; use 2 for headroom) | 1 GPU (~190 GB) |
| qwen3.6-27b | BF16 | 54 GB | 59 GB | 1 GPU (~66 GB) | 1 GPU (~200 GB) |
| qwen3.6-27b | FP8 | 27 GB | 30 GB | 1 GPU (~96 GB) | 1 GPU (~230 GB) |
| nemotron-3.5-lightning-30b | BF16 | 60 GB | 66 GB | 1 GPU (~60 GB; 2 for headroom) | 1 GPU (~195 GB) |
| nemotron-3.5-lightning-30b | FP8 / FP4 | 30 / 16 GB | 33 / 17 GB | 1 GPU | 1 GPU |
| gemma-4-31b | BF16 | 61 GB | 68 GB | 1 GPU (~58 GB; 2 for headroom) | 1 GPU (~190 GB) |
| gemma-4-31b | FP8 | 31 GB | 34 GB | 1 GPU (~92 GB) | 1 GPU (~225 GB) |
| muse-glimmer-30b | BF16 | 59 GB | 65 GB | 1 GPU (~61 GB) | 1 GPU (~195 GB) |

Notes:

- **FP8/FP4 rows are only worth it if a checkpoint exists.** Use a vendor- or
  community-published quantized checkpoint, or let vLLM quantize at load time
  (`--quantization fp8`). Changing precision changes the model you are scoring: record it
  in the `quantization` field of `agents-meta.jsonl` and do not mix precisions inside one
  comparison. The shipped rows serve BF16 (and MXFP4 for gpt-oss, as released).
- **Muse Glimmer must run with TP=1.** TP=2 fails on a vision-projector shape mismatch
  (`tools/serving/README.md`). It also needs the vLLM fork built by
  `setup_venv.sh --muse-fork` until upstream support lands.
- **Gemma 4 needed an older vLLM (0.21.x) in our testing** (a newer one fails on a
  per-layer `head_dim` check; see `tools/serving/README.md`). `serve_local.sh` runs it in
  Docker; set `ZBENCH_VLLM_IMAGE` to a 0.21 image tag. Whether that older build supports
  Blackwell (B300) is **unverified**; if it does not, serve Gemma on H200 or look for a
  newer vLLM release that fixed the issue.
- **Blackwell needs a vLLM build with Blackwell kernels** (a recent CUDA 12.x/13 wheel or
  container). We have not validated the PyPI wheel that `setup_venv.sh` installs on B300;
  run `setup_venv.sh --verify`, then a real `serve_local.sh check` first.
- **Native FP4 (NVFP4) on B300** gives the largest memory saving for the MoE models; Hopper
  (H200) has no native FP4 compute, so FP4 weights there are a memory-only trick through a
  weight-only kernel, if your engine supports it at all.

### 3.2 Other open-weight models in `agents-meta.jsonl`

The roster also names open-weight models that were originally reached through a
third-party hosted API (DeepSeek V4 Pro / Flash, Kimi K3, GLM 5.2). Those rows are retired
or paused in `agents-meta.jsonl` and are **not** in `agents-matrix.jsonl`; to run them
yourself you add agent rows (section 5 of [`running-your-models.md`](running-your-models.md)).
They are far larger than the local five:

| Model | Total / active params | Format on the card | Weights | w+10% |
|---|---|---|---|---|
| DeepSeek-V4-Flash-0731 | ~304 B / not stated | FP8 (with some BF16/F32/INT8 tensors) | ~304 GB | ~335 GB |
| DeepSeek-V4-Pro | ~1.6 T / 49 B | FP4 (MoE experts) + FP8 (rest) | ~0.85-0.9 T bytes (estimate; read the safetensors size on the card) | ~0.95 TB |
| GLM-5.2 | ~753 B / not stated | BF16 / F32 listed | ~1.5 TB in BF16; ~750 GB FP8; ~400 GB FP4 | ~1.66 TB / 828 GB / 440 GB |
| Kimi-K3 | ~2.8 T / 104 B | MXFP4 weights (quantization-aware trained), 1M context | ~1.5 TB as shipped | ~1.63 TB |

Minimum GPU count, same method (leave >= ~60 GB KV; "comfortable" = at least 30% of the
pool free):

| Model | Format | H200 minimum | B300 minimum | Notes |
|---|---|---|---|---|
| DeepSeek-V4-Flash | FP8 | 4 (TP=4, ~170 GB KV); 8 for comfort | 2 (~190 GB KV); 4 for comfort | native FP8 on both |
| DeepSeek-V4-Pro | FP4 + FP8 mixed | 16 (2 nodes); 8 GPUs leaves only ~45 GB | 4 (~75 GB KV, tight); 8 for comfort | the FP4 experts run natively only on B300 |
| GLM-5.2 | FP8 (needs a FP8 checkpoint or online quantization) | 8 (~175 GB KV) | 4 (~215 GB KV); 8 for comfort | BF16 needs 16 H200 or 8 B300 |
| Kimi-K3 | MXFP4 as shipped | 16 (2 nodes), only if your engine can run MXFP4 weights on Hopper; FP8 conversion (~2.8 TB) needs 32+ | 8 (one node, ~455 GB KV) | the clear B300 case |

Active-parameter counts matter for speed, and several are "not stated" on the cards read;
do not infer throughput for those models from total size.

### 3.3 Launch templates

Single GPU (`TP=1`), any of the 27-31 B models:

```bash
# <hf-repo> e.g. Qwen/Qwen3.6-27B; <alias> is what the agent row calls it (PI_MODEL)
CUDA_VISIBLE_DEVICES=0 vllm serve <hf-repo> \
  --served-model-name <alias> \
  --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.92 \
  --max-model-len 131072 \
  --enable-auto-tool-choice --tool-call-parser <parser> [--reasoning-parser <parser>]
```

Multi-GPU MoE (e.g. one 8-GPU node):

```bash
vllm serve <hf-repo> --served-model-name <alias> \
  --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size 8 --enable-expert-parallel \
  --gpu-memory-utilization 0.92 --max-model-len 131072 \
  --enable-auto-tool-choice --tool-call-parser <parser> [--reasoning-parser <parser>]
```

Rules that came out of the shipped serving recipe (`tools/serving/models.conf`):

- **Every server needs `--enable-auto-tool-choice` AND a `--tool-call-parser`.** Without
  both, any request that includes `tools` returns HTTP 400 and the agent harnesses cannot
  work. The parser names the shipped rows use are in `models.conf`
  (`openai`, `qwen3_coder`, `gemma4`, `muse_glimmer`; reasoning parsers `qwen3`,
  `nemotron_v3`, `gemma4`, `muse_glimmer`). For a new model, read the parser list from the
  vLLM you installed (`vllm serve --help`), not from docs.
- **`--served-model-name` must equal the agent row's `PI_MODEL`**
  (or `CODEX_MODEL_NAME`).
- **Prove tool calling works**: `bash tools/serving/serve_local.sh check`. A server that
  answers `/health` can still be useless to the harness.
- `--host 0.0.0.0` exposes the server to your network. `serve_local.sh` binds
  `127.0.0.1`; keep it that way unless the harness runs on another machine, and then
  restrict access with a firewall or tunnel. The server has no authentication by default.
- SGLang is an acceptable alternative engine (OpenAI-compatible, tool calling, expert
  parallelism), but the shipped scripts and the parser names above are vLLM-specific and
  we have not run the roster on SGLang. Record the engine and version per row.

### 3.4 Example `models.conf` for one 8-GPU node

Because each of the five local models fits on one GPU (see 3.1), one 8-GPU H200 or B300
node can host **all five at once** on separate GPUs. This is the one case where
co-hosting is clearly safe. Edit `tools/serving/models.conf` (format:
`alias | hf_repo | stack | gpus | port | tp | max_len | extra_flags`):

```
gpt-oss-120b|openai/gpt-oss-120b|venv|0|8010|1|131072|--enable-auto-tool-choice --tool-call-parser openai
qwen3.6-27b|Qwen/Qwen3.6-27B|venv|1|8011|1|131072|--enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3
nemotron-3.5-lightning-30b|nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16|venv|2|8012|1|131072|--enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser nemotron_v3
gemma-4-31b|google/gemma-4-31B-it|docker|3|8013|1|131072|--max-num-batched-tokens 8192 --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4
muse-glimmer-30b|meta-models/Muse-Glimmer-30B|venv:vllm-muse|4|8014|1|131072|--enable-auto-tool-choice --tool-call-parser muse_glimmer --reasoning-parser muse_glimmer
```

On H200 this leaves roughly 58-66 GB of KV per GPU for the BF16 models: enough to run,
but if you see preemptions in the vLLM log, give that model two GPUs (`gpus` = `1,2`,
`tp` = 2) as the repo's reference config does for the larger rows. The ports 8010-8014
match the `vllm-*` provider names the shipped `pi-vllm-*` rows expect (see
[`running-your-models.md`](running-your-models.md) section 4).

## 4. Throughput and time-per-task caveats

- **Wall-clock per task is dominated by decoding many turns over long context**, not by a
  single request. A task is tens of tool-using turns; each turn re-reads a growing
  history. Prefix caching (on by default in current vLLM) is what keeps this tractable;
  watch the cache hit rate (`tools/vllm_cache_stats.py`).
- **Active parameters set decode speed; total parameters set memory.** A 117 B MoE with
  5 B active decodes much faster than a 31 B dense model, while needing about twice the
  memory. A giant MoE (e.g. 2.8 T total / 104 B active) is memory-bound across many GPUs
  and its speed is governed by interconnect as much as by compute.
- **Estimate the full run before you start**:
  `wall_hours = n_tasks x minutes_per_task / parallel_cells / 60`. Get
  `minutes_per_task` from a 3-5 task smoke run of that exact model on your hardware
  (`tools/run_eval.sh --tasks 5 --agent 'pi-vllm-<model>' --go`), because it varies
  several-fold between models and with your engine settings. The per-attempt wall-clock
  cap is `ZBENCH_AGENT_TIMEOUT` (4800 s for the shipped local rows); slow models that hit
  the cap score as non-resolves, so check your hardware can finish a typical task inside
  it before you rank anything.
- **Parallelism is limited by KV memory, not by the harness.** More concurrent cells on
  one server means more KV in use; if vLLM starts preempting requests, lower the provider
  cap for that endpoint (`ZBENCH_SLOT_CAP_provider__<pool>`; see RUNBOOK "Concurrency &
  slots") rather than letting it thrash.
- **Reasoning effort is not controllable on these rows.** `PI_THINKING` does not reach a
  vLLM backend, so local rows are effort-uncontrolled (`effort_evidence: not_delivered`
  in `agents-meta.jsonl`). A model that thinks very long can also exhaust its completion
  budget and return an empty answer, which scores as a non-resolve; check this before you
  read a low score as low capability.
- Quantizing, changing `--kv-cache-dtype`, or switching engines changes results. Treat
  each as a different agent and record it.

## 5. One model at a time, unless memory allows co-hosting

Default to **serving one model, running its agents to completion, stopping it, then
serving the next.** It keeps the memory arithmetic simple and removes cross-model
interference in timing. Co-host only when the arithmetic in section 1 is satisfied for
**every** model on **disjoint GPUs** (section 3.4 is the safe case: five single-GPU models
on five GPUs). Never co-host two models on the same GPU to "fit more"; the second one's
KV cache will starve the first, and the resulting preemptions look like slow or
low-quality models.

```bash
bash tools/serving/serve_local.sh start gpt-oss-120b     # one alias
bash tools/serving/serve_local.sh status
bash tools/serving/serve_local.sh check gpt-oss-120b     # tool-calling proof
# ... run that model's agents ...
bash tools/serving/serve_local.sh stop gpt-oss-120b
```

## 6. Sizing a model that is not in the table

1. Read total and active parameters and the weight dtype from the model card.
2. `weights_GB = params_B x bytes_per_param`; multiply by 1.10.
3. Compute `KV_GB_per_sequence` from `config.json` (section 2) for 131,072 tokens and
   decide how many concurrent sequences you want (start with 4).
4. `n_gpus = ceil((1.10 x weights + 4 x n_gpus + 4 x KV_seq) / usable_per_GPU)`, then round
   up to a valid TP size (1, 2, 4, 8) or to whole nodes.
5. Look up the tool-call and reasoning parser names in the installed vLLM, add a line to
   `models.conf`, `start`, then `check`.
6. Add the `agents-meta.jsonl` row (engine version, quantization, GPU count, parser) so
   the result is interpretable later.
